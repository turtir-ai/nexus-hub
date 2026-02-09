#!/usr/bin/env python3
"""NEXUS V3.5.0 fix queue with deterministic verification loop."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

RUNTIME_DIR = pathlib.Path(os.environ.get("CLAUDE_PLUGIN_ROOT", pathlib.Path(__file__).resolve().parents[1]))
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_verify_cmd(project_root: str) -> List[str]:
    return ["python3", "-m", "compileall", "-q", str(project_root)]


class FixQueue:
    """Queue for fix tasks generated from incidents."""

    def __init__(self, state_dir: Optional[pathlib.Path] = None):
        self.state_dir = state_dir or (pathlib.Path.home() / ".claude" / "state")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.fix_queue_file = self.state_dir / "fix_queue.jsonl"

    def _load_tasks(self) -> List[Dict[str, Any]]:
        if not self.fix_queue_file.exists():
            return []

        tasks: List[Dict[str, Any]] = []
        with self.fix_queue_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    tasks.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
        return tasks

    def _write_tasks(self, tasks: List[Dict[str, Any]]) -> None:
        with self.fix_queue_file.open("w", encoding="utf-8") as handle:
            for task in tasks:
                handle.write(json.dumps(task, ensure_ascii=False, default=str) + "\n")

    def add_fix_task(
        self,
        incident: Dict[str, Any],
        suggested_fix: str,
        verify_cmd: List[str],
        created_by: str = "self_heal",
        meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        task_id = f"fix_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        task = {
            "id": task_id,
            "timestamp": _now_iso(),
            "incident": incident,
            "suggested_fix": suggested_fix,
            "verify_cmd": verify_cmd,
            "status": "pending",  # pending|attempted|completed|failed
            "attempts": 0,
            "created_by": created_by,
            "meta": meta or {},
            "history": [
                {
                    "timestamp": _now_iso(),
                    "status": "pending",
                    "note": "task_created",
                }
            ],
        }

        with self.fix_queue_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(task, ensure_ascii=False, default=str) + "\n")

        return task_id

    def get_next_fix(self) -> Optional[Dict[str, Any]]:
        for task in self._load_tasks():
            if task.get("status") == "pending":
                return task
        return None

    def update_task_status(
        self,
        task_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> bool:
        tasks = self._load_tasks()
        updated = False

        for task in tasks:
            if task.get("id") != task_id:
                continue
            task["status"] = status
            if status == "attempted":
                task["attempts"] = int(task.get("attempts", 0)) + 1
            task["last_updated"] = _now_iso()
            if result is not None:
                task["result"] = result
            task.setdefault("history", []).append(
                {
                    "timestamp": _now_iso(),
                    "status": status,
                    "result": result or {},
                }
            )
            updated = True

        if not updated:
            return False

        self._write_tasks(tasks)
        self._record_pattern_for_status(task_id, status, result)
        return True

    def _record_pattern_for_status(
        self,
        task_id: str,
        status: str,
        result: Optional[Dict[str, Any]],
    ) -> None:
        if status not in {"completed", "failed"}:
            return

        try:
            from state_manager import get_state_manager

            sm = get_state_manager()
            tasks = self._load_tasks()
            task = next((item for item in tasks if item.get("id") == task_id), None)
            if not task:
                return

            incident = task.get("incident", {})
            signature = (
                incident.get("signature")
                or incident.get("failed_check")
                or incident.get("incident_class")
                or "fix_task"
            )
            outcome = "success" if status == "completed" else "failure"
            pattern_type = f"fix_task_{status}"
            sm.add_pattern(
                pattern_type=pattern_type,
                signature=signature,
                example={
                    "task_id": task_id,
                    "incident": incident,
                    "result": result or {},
                },
                suggested_fix=task.get("suggested_fix", ""),
                verify_cmd=task.get("verify_cmd", []),
                outcome=outcome,
                meta={"status": status},
            )
        except Exception:
            return

    def process_one_task(self, executor: str = "manual") -> Dict[str, Any]:
        task = self.get_next_fix()
        if not task:
            return {"status": "no_pending_task"}

        task_id = task["id"]
        verify_cmd = task.get("verify_cmd") or ["echo", "missing_verify_cmd"]

        self.update_task_status(task_id, "attempted", {"executor": executor, "verify_cmd": verify_cmd})

        start = time.time()
        proc = subprocess.run(
            verify_cmd,
            text=True,
            capture_output=True,
            timeout=300,
        )
        duration = round(time.time() - start, 4)

        success = proc.returncode == 0
        final_status = "completed" if success else "failed"
        result = {
            "executor": executor,
            "verify_cmd": verify_cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
            "duration_sec": duration,
        }
        self.update_task_status(task_id, final_status, result)

        try:
            from state_manager import get_state_manager

            sm = get_state_manager()
            sm.record_fix_verification(success=success, duration_seconds=duration)
        except Exception:
            pass

        return {
            "status": final_status,
            "task_id": task_id,
            "verify_cmd": verify_cmd,
            "returncode": proc.returncode,
            "duration_sec": duration,
        }

    def get_stats(self) -> Dict[str, int]:
        counts = {
            "pending": 0,
            "attempted": 0,
            "completed": 0,
            "failed": 0,
            "total": 0,
        }

        for task in self._load_tasks():
            status = task.get("status", "pending")
            if status not in counts:
                counts[status] = 0
            counts[status] += 1
            counts["total"] += 1

        return counts


def _incident_to_fix_plan(incident: Dict[str, Any]) -> Dict[str, Any]:
    error_text = " ".join(
        [
            str(incident.get("error", "")),
            str(incident.get("signature", "")),
            str(incident.get("failed_check", "")),
            str(incident.get("incident_class", "")),
        ]
    ).lower()

    cwd = str(incident.get("cwd") or pathlib.Path.cwd())
    tool_input = incident.get("tool_input") if isinstance(incident.get("tool_input"), dict) else {}
    file_path = tool_input.get("file_path") or tool_input.get("path") or incident.get("file_path")

    if "ruff" in error_text or "f401" in error_text:
        target = file_path or cwd
        return {
            "suggested_fix": "Remove unused imports/variables then rerun ruff.",
            "verify_cmd": ["ruff", "check", str(target)],
        }

    if "pytest" in error_text or "assert" in error_text or "test" in error_text:
        return {
            "suggested_fix": "Fix failing tests and rerun pytest.",
            "verify_cmd": ["pytest", "-q"],
        }

    if "syntax" in error_text or "compile" in error_text:
        if file_path:
            return {
                "suggested_fix": f"Fix Python syntax errors in {file_path}.",
                "verify_cmd": ["python3", "-m", "py_compile", str(file_path)],
            }
        return {
            "suggested_fix": "Fix Python syntax errors detected by compileall.",
            "verify_cmd": ["python3", "-m", "compileall", "-q", cwd],
        }

    if "module" in error_text or "import" in error_text:
        module_name = incident.get("module_name") or "<missing_module>"
        return {
            "suggested_fix": f"Install or vendor missing module `{module_name}` and verify import.",
            "verify_cmd": ["python3", "-c", f"import {module_name}"] if module_name != "<missing_module>" else ["python3", "-m", "compileall", "-q", cwd],
        }

    if "permission" in error_text:
        target = file_path or cwd
        return {
            "suggested_fix": f"Adjust file permissions for `{target}`.",
            "verify_cmd": ["test", "-r", str(target)],
        }

    if "not found" in error_text or "no such file" in error_text:
        target = file_path or cwd
        return {
            "suggested_fix": f"Create or correct missing path `{target}`.",
            "verify_cmd": ["test", "-e", str(target)],
        }

    return {
        "suggested_fix": "Investigate incident details and apply a minimal deterministic fix.",
        "verify_cmd": _default_verify_cmd(cwd),
    }


def add_fix_from_incident(incident: Dict[str, Any]) -> str:
    queue = FixQueue()
    plan = _incident_to_fix_plan(incident)
    return queue.add_fix_task(
        incident=incident,
        suggested_fix=plan["suggested_fix"],
        verify_cmd=plan["verify_cmd"],
    )


if __name__ == "__main__":
    fq = FixQueue()
    print(json.dumps(fq.get_stats(), indent=2))
