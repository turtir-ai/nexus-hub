#!/usr/bin/env python3
"""SessionStart hook for NEXUS core plugin.

Responsibilities (stdlib only, no daemons):
- Record plugin runtime location/version for portability
- Increment session metrics + update MSV project context
- Refresh mental model scan with safe ignore rules (throttled)
- Inject "Codex-grade" additionalContext for more deterministic outputs
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from _hook_io import (
    get_plugin_root,
    get_project_root,
    now_iso,
    read_hook_event,
    record_plugin_runtime,
)


def _safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _should_scan(project_key: str, mental_model: Dict[str, Any], min_interval_sec: int) -> bool:
    try:
        projects = mental_model.get("projects") if isinstance(mental_model, dict) else {}
        entry = projects.get(project_key) if isinstance(projects, dict) else None
        last = (entry or {}).get("last_scan")
        if not last:
            return True
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        now_dt = datetime.now(timezone.utc)
        return (now_dt - last_dt).total_seconds() >= float(min_interval_sec)
    except Exception:
        return True


def _build_additional_context(project_root: Path, scan_summary: Dict[str, Any] | None) -> str:
    scan = scan_summary or {}
    project_type = scan.get("project_type", "unknown")
    file_count = scan.get("file_count")
    file_info = f"{file_count} files" if isinstance(file_count, int) else "unknown size"

    # Keep this short but strict: it's there to steer weaker models toward disciplined behavior.
    return (
        f"You are running inside Claude Code with the NEXUS core plugin enabled (hook-driven).\n"
        f"Current project root: {project_root} ({project_type}, {file_info}).\n\n"
        "NEXUS Operating Contract (must follow):\n"
        "1. Evidence-first: read files / run commands before edits.\n"
        "2. Minimal diffs: smallest targeted patch that solves the problem.\n"
        "3. Deterministic verification: run tests/lint/compile after meaningful changes.\n"
        "4. No hype: never claim something works without command output.\n"
        "5. If a gate fails: stop, fix, and re-verify before proceeding.\n\n"
        "Output Contract (always this order):\n"
        "1) What I changed\n"
        "2) Evidence (exact commands + key output)\n"
        "3) File list\n"
        "4) Next command\n\n"
        "Notes:\n"
        "- PostToolUse quality gate may rollback on failure and will create incident/fix tasks.\n"
        "- Use NEXUS state under ~/.claude/state as the source of truth for metrics and incidents.\n"
        "- If you must run a standalone command outside Claude tools, prefer running it through\n"
        "  the local NEXUS bridge (if installed) to preserve evidence: `python3 ~/.claude/nexus_exec.py -- <cmd>`.\n"
    )


def main() -> int:
    try:
        event = read_hook_event()
        plugin_root = get_plugin_root()
        record_plugin_runtime(plugin_root=plugin_root)

        # Make plugin code importable when called as a hook.
        if str(plugin_root) not in sys.path:
            sys.path.insert(0, str(plugin_root))

        from project_scan import find_project_root, scan_project
        from state_manager import get_state_manager

        cwd = get_project_root(event)
        project_root = find_project_root(cwd)

        sm = get_state_manager()

        # Metrics: session count
        metrics = sm.load_metrics()
        metrics["session_count"] = int(metrics.get("session_count", 0) or 0) + 1
        sm.save_metrics(metrics)

        # MSV context update
        msv = sm.load_msv()
        msv.setdefault("context", {})["current_project"] = str(project_root)
        msv.setdefault("context", {}).setdefault("agent_status", {})["nexus"] = "active"
        sm.save_msv(msv)

        scan_min_interval = _safe_int(os.environ.get("NEXUS_SCAN_MIN_INTERVAL_SEC", "600"), 600)
        scan_summary: Dict[str, Any] | None = None
        mental_model = sm.load_mental_model()
        project_key = str(project_root)
        if _should_scan(project_key, mental_model, scan_min_interval):
            scan_summary = scan_project(project_root)
            projects = mental_model.setdefault("projects", {})
            projects[project_key] = {
                **{k: v for k, v in scan_summary.items() if k != "root"},
                "last_scan": scan_summary.get("scanned_at"),
            }
            mental_model["current_project"] = project_key
            mental_model["last_scan"] = {
                "timestamp": scan_summary.get("scanned_at"),
                "file_count": scan_summary.get("file_count"),
                "project_type": scan_summary.get("project_type"),
            }
            sm.save_mental_model(mental_model)
            sm.record_event("mental_model_scan", {"root": project_key, "summary": mental_model["last_scan"]})

        sm.record_event(
            "session_start",
            {
                "cwd": str(cwd),
                "project_root": str(project_root),
                "timestamp": now_iso(),
            },
        )

        out = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": _build_additional_context(project_root, scan_summary),
            }
        }
        print(json.dumps(out, ensure_ascii=False))
        return 0
    except Exception:
        # Never break the session.
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

