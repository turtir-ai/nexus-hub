#!/usr/bin/env python3
"""Task lifecycle tracking for NEXUS V3.5.0."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


class TaskManager:
    """Manage current task pointer and append-only task lifecycle log."""

    def __init__(self):
        self.claude_dir = pathlib.Path.home() / ".claude"
        self.state_dir = self.claude_dir / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_log = self.state_dir / "tasks.jsonl"
        self.current_task_file = self.state_dir / "current_task.json"

        # Code lives in the plugin; state lives in ~/.claude.
        runtime_dir = pathlib.Path(
            os.environ.get("CLAUDE_PLUGIN_ROOT", pathlib.Path(__file__).resolve().parent)
        )
        if str(runtime_dir) not in sys.path:
            sys.path.insert(0, str(runtime_dir))

        from state_manager import get_state_manager

        self.sm = get_state_manager()

    def _append_task_event(self, event: Dict[str, Any]) -> None:
        event.setdefault("timestamp", _now_iso())
        with self.tasks_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def _load_current_task(self) -> Optional[Dict[str, Any]]:
        if not self.current_task_file.exists():
            return None
        try:
            data = json.loads(self.current_task_file.read_text())
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or not data:
            return None
        if data.get("status") != "active":
            return None
        return data

    def _save_current_task(self, task: Dict[str, Any]) -> None:
        self.current_task_file.write_text(json.dumps(task, indent=2, ensure_ascii=False))

    def get_current_task(self) -> Optional[Dict[str, Any]]:
        return self._load_current_task()

    def start_task(self, goal: str) -> Dict[str, Any]:
        current = self._load_current_task()
        if current:
            raise RuntimeError(f"Active task already exists: {current.get('id')}")

        task = {
            "id": f"task_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
            "goal": goal,
            "status": "active",
            "started_at": _now_iso(),
            "updated_at": _now_iso(),
            "progress_events": 0,
            "notes": [],
        }
        self._save_current_task(task)

        self._append_task_event({"event": "task_started", "task": task})
        self.sm.record_event("task_started", {"task_id": task["id"], "goal": goal})

        msv = self.sm.load_msv()
        msv.setdefault("context", {})["active_task"] = task["id"]
        self.sm.save_msv(msv)
        return task

    def close_task(self, success: bool, note: str = "") -> Dict[str, Any]:
        task = self._load_current_task()
        if not task:
            raise RuntimeError("No active task")

        ended_at = _now_iso()
        started = _parse_iso(task.get("started_at"))
        ended = _parse_iso(ended_at)
        duration_sec = round((ended - started).total_seconds(), 4) if started and ended else 0.0

        closed = {
            **task,
            "status": "completed" if success else "failed",
            "ended_at": ended_at,
            "duration_sec": duration_sec,
            "close_note": note,
            "updated_at": ended_at,
        }

        self._append_task_event({"event": "task_closed", "task": closed})
        self.sm.record_event(
            "task_closed",
            {
                "task_id": task["id"],
                "success": success,
                "duration_sec": duration_sec,
                "note": note,
            },
        )
        self.sm.record_task_close(success=success, duration_seconds=duration_sec)

        if self.current_task_file.exists():
            self.current_task_file.unlink()

        msv = self.sm.load_msv()
        msv.setdefault("context", {})["active_task"] = None
        self.sm.save_msv(msv)

        return closed

    def record_quality_gate_pass(
        self,
        event: Dict[str, Any],
        root: pathlib.Path,
        checks: Optional[list] = None,
    ) -> Optional[Dict[str, Any]]:
        task = self._load_current_task()
        if not task:
            return None

        task["progress_events"] = int(task.get("progress_events", 0)) + 1
        task["updated_at"] = _now_iso()
        task["last_quality_gate_pass_at"] = _now_iso()
        task.setdefault("recent_checks", []).append({"ts": _now_iso(), "checks": checks or []})
        if len(task["recent_checks"]) > 10:
            del task["recent_checks"][:-10]

        self._save_current_task(task)
        self._append_task_event(
            {
                "event": "task_progress",
                "task_id": task["id"],
                "tool_name": event.get("tool_name", ""),
                "cwd": str(root),
                "checks": checks or [],
            }
        )

        metrics = self.sm.load_metrics()
        metrics["task_progress_events"] = int(metrics.get("task_progress_events", 0)) + 1
        self.sm.save_metrics(metrics)

        # Optional Rule B (disabled by default).
        if os.environ.get("NEXUS_TASK_AUTO_CLOSE", "0") == "1":
            min_passes = int(os.environ.get("NEXUS_TASK_AUTO_CLOSE_MIN_PASSES", "3"))
            if int(task.get("progress_events", 0)) >= min_passes:
                failure_at = _parse_iso(task.get("last_quality_gate_fail_at"))
                now = _parse_iso(_now_iso())
                safe_to_close = True
                if failure_at and now:
                    safe_to_close = (now - failure_at).total_seconds() > 600
                if safe_to_close:
                    return self.close_task(success=True, note="auto-closed after repeated quality_gate passes")

        return task

    def record_quality_gate_fail(self, signature: str = "") -> Optional[Dict[str, Any]]:
        task = self._load_current_task()
        if not task:
            return None

        task["updated_at"] = _now_iso()
        task["last_quality_gate_fail_at"] = _now_iso()
        task.setdefault("notes", []).append(f"quality_gate_fail:{signature}")
        if len(task["notes"]) > 20:
            del task["notes"][:-20]
        self._save_current_task(task)
        return task

    def status(self) -> Dict[str, Any]:
        from hooks.fix_queue import FixQueue

        current = self._load_current_task()
        metrics = self.sm.load_metrics()
        fix_stats = FixQueue().get_stats()
        return {
            "current_task": current,
            "metrics": metrics,
            "fix_queue": fix_stats,
        }
