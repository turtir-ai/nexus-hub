#!/usr/bin/env python3
"""NEXUS V3.5.0 quality gate with learning, incidents, and fix queue integration."""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from _hook_io import get_project_root, now_iso, read_hook_event

# Code lives in this plugin; state lives in ~/.claude.
CLAUDE_DIR = pathlib.Path.home() / ".claude"
RUNTIME_DIR = pathlib.Path(os.environ.get("CLAUDE_PLUGIN_ROOT", pathlib.Path(__file__).resolve().parents[1]))
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from state_manager import get_state_manager
from task_manager import TaskManager

try:
    from fix_queue import add_fix_from_incident
except Exception:
    # Fallback import path when invoked outside hooks directory.
    import importlib.util

    spec = importlib.util.spec_from_file_location("fix_queue", RUNTIME_DIR / "hooks" / "fix_queue.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    add_fix_from_incident = module.add_fix_from_incident


STATE_DIR = CLAUDE_DIR / "state"
SNAP_DIR = STATE_DIR / "snapshots"
SNAP_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run(cmd: List[str], cwd: pathlib.Path | None = None, timeout: int = 300) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)
        return proc.returncode, proc.stdout[-4000:], proc.stderr[-4000:]
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"timeout: {exc}"


def git_present(root: pathlib.Path) -> bool:
    return (root / ".git").exists()


def find_project_root(start: pathlib.Path) -> pathlib.Path:
    cur = start.resolve()
    for _ in range(20):
        if (cur / ".git").exists() or (cur / "pyproject.toml").exists() or (cur / "package.json").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.resolve()


def git_diff_stats(root: pathlib.Path) -> Dict[str, Any]:
    if not git_present(root):
        return {"lines_added": 0, "lines_deleted": 0, "files": 0, "raw": ""}

    rc, out, err = run(["git", "diff", "--numstat"], cwd=root)
    if rc != 0:
        return {"lines_added": 0, "lines_deleted": 0, "files": 0, "raw": err}

    added = deleted = files = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        if parts[0].isdigit():
            added += int(parts[0])
        if parts[1].isdigit():
            deleted += int(parts[1])
        files += 1

    return {"lines_added": added, "lines_deleted": deleted, "files": files, "raw": out}


def changed_files_summary(root: pathlib.Path, event: Dict[str, Any]) -> Dict[str, Any]:
    changed: List[str] = []

    if git_present(root):
        rc, out, _ = run(["git", "diff", "--name-only"], cwd=root)
        if rc == 0:
            changed.extend([line.strip() for line in out.splitlines() if line.strip()])

    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    candidate = tool_input.get("file_path") or tool_input.get("path")
    if candidate:
        try:
            candidate_path = pathlib.Path(candidate)
            if candidate_path.is_absolute():
                rel = candidate_path.resolve().relative_to(root.resolve())
            else:
                rel = candidate_path
            changed.append(str(rel))
        except Exception:
            pass

    unique = []
    seen = set()
    for item in changed:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)

    return {
        "count": len(unique),
        "files": unique[:50],
    }


def snapshot_files(root: pathlib.Path, changed_files: List[str]) -> pathlib.Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    snap = SNAP_DIR / ts
    snap.mkdir(parents=True, exist_ok=True)

    manifest = {"timestamp": ts, "root": str(root), "files": []}
    for rel in changed_files[:200]:
        source = (root / rel).resolve()
        if source.exists() and source.is_file():
            target = snap / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            manifest["files"].append(rel)

    (snap / "_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return snap


def rollback(root: pathlib.Path, snap_path: pathlib.Path) -> str:
    if git_present(root):
        run(["git", "checkout", "--", "."], cwd=root)
        return "git_checkout"

    manifest_path = snap_path / "_manifest.json"
    if not manifest_path.exists():
        return "snapshot_missing"

    manifest = json.loads(manifest_path.read_text())
    for rel in manifest.get("files", []):
        source = snap_path / rel
        target = root / rel
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return "snapshot_restore"


def _detect_stack(root: pathlib.Path, changed_summary: Dict[str, Any]) -> Tuple[bool, bool]:
    changed = changed_summary.get("files", [])
    has_py_change = any(path.endswith(".py") for path in changed)
    has_js_change = any(path.endswith((".js", ".ts", ".tsx", ".jsx")) for path in changed)

    is_python = (root / "pyproject.toml").exists() or (root / "requirements.txt").exists() or has_py_change
    is_node = (root / "package.json").exists() or has_js_change
    return is_python, is_node


def _signature_from_output(check_name: str, stdout: str, stderr: str, detail: Dict[str, Any]) -> str:
    output = f"{stdout}\n{stderr}"
    if check_name == "ruff":
        match = re.search(r"\b([A-Z]{1,4}\d{3,4})\b", output)
        return f"ruff:{match.group(1)}" if match else "ruff:fail"
    if check_name == "pytest":
        return "pytest:fail"
    if check_name == "py_compileall":
        if "SyntaxError" in output:
            return "compileall:SyntaxError"
        return "compileall:fail"
    if check_name == "npm_test":
        return "npm_test:fail"
    if check_name == "diff_limit":
        return f"diff:limit_exceeded:{detail.get('delta', 'unknown')}"
    return f"{check_name}:fail"


def _check_result(name: str, ok: bool, detail: Dict[str, Any], stdout: str = "", stderr: str = "") -> Dict[str, Any]:
    signature = "" if ok else _signature_from_output(name, stdout, stderr, detail)
    return {
        "name": name,
        "ok": ok,
        "signature": signature,
        "detail": detail,
        "stdout": stdout,
        "stderr": stderr,
    }


def quality_checks(root: pathlib.Path, changed_summary: Dict[str, Any], diff_limit: int = 200) -> Tuple[bool, List[Dict[str, Any]]]:
    checks: List[Dict[str, Any]] = []

    if git_present(root):
        stats = git_diff_stats(root)
        delta = int(stats.get("lines_added", 0)) + int(stats.get("lines_deleted", 0))
        checks.append(_check_result("diff_limit", delta <= diff_limit, {"delta": delta, **stats}))

    is_python, is_node = _detect_stack(root, changed_summary)

    if is_python:
        if shutil.which("ruff"):
            rc, out, err = run(["ruff", "check", "."], cwd=root)
            checks.append(_check_result("ruff", rc == 0, {"returncode": rc}, out, err))

        if shutil.which("pytest") and any((root / name).exists() for name in ["tests", "test"]):
            rc, out, err = run(["pytest", "-q"], cwd=root, timeout=900)
            checks.append(_check_result("pytest", rc == 0, {"returncode": rc}, out, err))

        rc, out, err = run([sys.executable, "-m", "compileall", "-q", str(root)], cwd=root, timeout=300)
        checks.append(_check_result("py_compileall", rc == 0, {"returncode": rc}, out, err))

    if is_node and (root / "package.json").exists() and shutil.which("npm"):
        rc, out, err = run(["npm", "test", "--silent"], cwd=root, timeout=900)
        checks.append(_check_result("npm_test", rc == 0, {"returncode": rc}, out, err))

    passed = all(check["ok"] for check in checks) if checks else True
    return passed, checks


def _first_failed_check(checks: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    for check in checks:
        if not check.get("ok"):
            return check
    return None


def _failure_guidance(failed_check: Dict[str, Any]) -> str:
    name = failed_check.get("name")
    if name == "ruff":
        return "Resolve lint violations (example: unused imports) and rerun `ruff check .`."
    if name == "pytest":
        return "Fix failing tests and rerun `pytest -q`."
    if name == "py_compileall":
        return "Fix Python syntax/type issues and rerun compile check."
    if name == "npm_test":
        return "Fix JavaScript/TypeScript test failures and rerun npm tests."
    if name == "diff_limit":
        return "Split the change into smaller commits under the diff limit."
    return "Review the failed quality check output and apply a minimal corrective patch."


def _summarize_checks(checks: List[Dict[str, Any]]) -> List[Tuple[str, bool]]:
    return [(check.get("name", "unknown"), bool(check.get("ok"))) for check in checks]


def main() -> int:
    if os.environ.get("NEXUS_GATE_RUNNING") == "1":
        print(json.dumps({"skipped": "recursion_guard"}))
        return 0
    os.environ["NEXUS_GATE_RUNNING"] = "1"

    start = time.time()
    event = read_hook_event()
    event_cwd = get_project_root(event)
    root = find_project_root(event_cwd)

    tool_name = event.get("tool_name") or "unknown_tool"
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}

    changed_summary = changed_files_summary(root, event)
    snap = snapshot_files(root, changed_summary.get("files", []))
    passed, checks = quality_checks(root, changed_summary, diff_limit=200)

    sm = get_state_manager()
    metrics = sm.load_metrics()
    rollback_before = int(metrics.get("rollback_count", 0))
    metrics["runs"] = int(metrics.get("runs", 0)) + 1
    metrics["last_run"] = _now_iso()
    metrics["last_result"] = {
        "passed": passed,
        "checks": _summarize_checks(checks),
        "tool_name": tool_name,
    }

    failed_check = _first_failed_check(checks)
    rollback_method = None

    if not passed and failed_check:
        metrics["rollback_count"] = rollback_before + 1
        metrics["last_failed_check"] = failed_check.get("name")

    sm.save_metrics(metrics)

    rollback_after = int(sm.load_metrics().get("rollback_count", 0))

    if passed:
        signature = "quality_gate:all_checks_passed"
        suggested_action = "Continue implementation; keep changes small and covered by checks."
        pattern_type = "quality_gate_pass"
        outcome = "success"
    else:
        signature = failed_check.get("signature") if failed_check else "quality_gate:unknown_fail"
        suggested_action = _failure_guidance(failed_check or {})
        pattern_type = "quality_gate_fail"
        outcome = "failure"

    sm.add_pattern(
        pattern_type=pattern_type,
        signature=signature,
        example={
            "tool_name": tool_name,
            "tool_input": tool_input,
            "changed_files": changed_summary,
            "checks": checks,
            "rollback_count_before": rollback_before,
            "rollback_count_after": rollback_after,
            "cwd": str(root),
        },
        suggested_fix=suggested_action,
        verify_cmd=["python3", str(RUNTIME_DIR / "hooks" / "quality_gate.py")],
        outcome=outcome,
        meta={
            "tool_name": tool_name,
            "changed_files_count": changed_summary.get("count", 0),
        },
    )

    task_manager = TaskManager()
    if passed:
        task_manager.record_quality_gate_pass(event=event, root=root, checks=_summarize_checks(checks))
    else:
        task_manager.record_quality_gate_fail(signature=signature)

    if not passed:
        rollback_method = rollback(root, snap)

        incident_id = f"inc_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        incident = {
            "id": incident_id,
            "timestamp": _now_iso(),
            "source": "quality_gate",
            "incident_class": failed_check.get("name") if failed_check else "quality_gate_failed",
            "failed_check": failed_check.get("name") if failed_check else "unknown",
            "signature": signature,
            "error": (failed_check or {}).get("stderr") or (failed_check or {}).get("stdout") or "quality gate failure",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_response": event.get("tool_response", {}),
            "cwd": str(root),
            "checks": checks,
            "rollback_method": rollback_method,
            "suggested_action": suggested_action,
        }

        sm.record_incident(incident)
        task_id = add_fix_from_incident(incident)

        out = {
            "passed": False,
            "rolled_back": True,
            "rollback_method": rollback_method,
            "checks": _summarize_checks(checks),
            "failed_signature": signature,
            "incident_id": incident_id,
            "fix_task_id": task_id,
            "root": str(root),
            "elapsed_sec": round(time.time() - start, 3),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 2

    out = {
        "passed": True,
        "checks": _summarize_checks(checks),
        "root": str(root),
        "elapsed_sec": round(time.time() - start, 3),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
