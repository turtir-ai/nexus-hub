#!/usr/bin/env python3
"""SessionEnd hook for NEXUS core plugin.

This is intentionally lightweight and deterministic:
- never runs background daemons
- never auto-edits project code
- writes evidence-friendly session log entries
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from _hook_io import get_plugin_root, get_project_root, now_iso, read_hook_event, record_plugin_runtime


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip("\n") + "\n")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _fix_queue_stats(state_dir: Path) -> Dict[str, int]:
    path = state_dir / "fix_queue.jsonl"
    counts = {"pending": 0, "attempted": 0, "completed": 0, "failed": 0, "total": 0}
    if not path.exists():
        return counts
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                task = json.loads(raw)
            except json.JSONDecodeError:
                continue
            status = str(task.get("status", "pending"))
            if status not in counts:
                counts[status] = 0
            counts[status] += 1
            counts["total"] += 1
    return counts


def main() -> int:
    try:
        event = read_hook_event()
        plugin_root = get_plugin_root()
        record_plugin_runtime(plugin_root=plugin_root)

        if str(plugin_root) not in sys.path:
            sys.path.insert(0, str(plugin_root))

        from project_scan import find_project_root
        from state_manager import get_state_manager

        cwd = get_project_root(event)
        project_root = find_project_root(cwd)

        sm = get_state_manager()
        state_dir = Path.home() / ".claude" / "state"
        metrics = sm.load_metrics()
        fix_stats = _fix_queue_stats(state_dir)
        current_task = _load_json(state_dir / "current_task.json")

        sm.record_event(
            "session_end",
            {
                "cwd": str(cwd),
                "project_root": str(project_root),
                "timestamp": now_iso(),
                "metrics": {
                    "tasks_completed": metrics.get("tasks_completed", 0),
                    "incidents_total": metrics.get("incidents_total", 0),
                    "rollback_count": metrics.get("rollback_count", 0),
                },
                "fix_queue": fix_stats,
            },
        )

        # Global session log (append-only)
        global_log = Path.home() / ".claude" / "logs" / "sessions.log"
        _append_line(
            global_log,
            f"SESSION_END: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z | DIR: {project_root}",
        )

        # Per-project memory log (append-only)
        mem_dir = project_root / ".claude" / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        session_log = mem_dir / "session_log.md"
        entry = [
            "",
            f"## Session End {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z",
            f"- Project: `{project_root}`",
            f"- Active task: `{current_task.get('id')}`" if current_task.get("id") else "- Active task: (none)",
            f"- Metrics: tasks_completed={metrics.get('tasks_completed', 0)} incidents_total={metrics.get('incidents_total', 0)} rollback_count={metrics.get('rollback_count', 0)}",
            f"- Fix queue: pending={fix_stats.get('pending', 0)} failed={fix_stats.get('failed', 0)} completed={fix_stats.get('completed', 0)}",
            "",
        ]
        _append_line(session_log, "\n".join(entry).rstrip("\n"))

        print(json.dumps({"ok": True}, ensure_ascii=False))
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

