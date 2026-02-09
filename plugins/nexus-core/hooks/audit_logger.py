#!/usr/bin/env python3
"""Audit logger hook with backward-compatible hook payload parsing."""
from __future__ import annotations

import json
import pathlib
import sys

from _hook_io import get_claude_dir, get_project_root, read_hook_event, safe_write_jsonl


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "event"
    event = read_hook_event()

    record = {
        "mode": mode,
        "cwd": str(get_project_root(event)),
        "tool_name": event.get("tool_name"),
        "tool_input": event.get("tool_input", {}),
        "tool_response": event.get("tool_response", {}),
        "event": event,
    }

    audit_file = get_claude_dir() / "logs" / "audit.jsonl"
    safe_write_jsonl(audit_file, record)

    print(json.dumps({"ok": True, "mode": mode}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
