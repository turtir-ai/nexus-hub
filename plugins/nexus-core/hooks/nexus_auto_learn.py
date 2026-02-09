#!/usr/bin/env python3
"""NEXUS V3.5.0 auto-learning hook with resilient PostToolUse parsing."""
from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Any, Dict

from _hook_io import get_project_root, read_hook_event

CLAUDE_DIR = pathlib.Path.home() / ".claude"
RUNTIME_DIR = pathlib.Path(os.environ.get("CLAUDE_PLUGIN_ROOT", pathlib.Path(__file__).resolve().parents[1]))
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from state_manager import get_state_manager


def _is_success(response: Dict[str, Any]) -> bool:
    if not isinstance(response, dict):
        return True
    if response.get("success") is False:
        return False
    exit_code = response.get("exit_code")
    if isinstance(exit_code, int) and exit_code != 0:
        return False
    return True


def _signature(tool_name: str, tool_input: Dict[str, Any], response: Dict[str, Any]) -> str:
    if tool_name == "Bash":
        command = tool_input.get("command") or tool_input.get("cmd") or ""
        return f"bash:{str(command).strip()[:80]}" if command else "bash:unknown"
    if tool_name in {"Edit", "Write", "Read"}:
        path = tool_input.get("file_path") or tool_input.get("path") or "unknown"
        return f"{tool_name.lower()}:{path}"
    if tool_name:
        return f"tool:{tool_name}"
    return "tool:unknown"


def main() -> int:
    event = read_hook_event()
    if not event:
        print("ok: empty_event")
        return 0

    sm = get_state_manager()

    tool_name = event.get("tool_name") or "unknown"
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    tool_response = event.get("tool_response") if isinstance(event.get("tool_response"), dict) else {}
    cwd = str(get_project_root(event))

    success = _is_success(tool_response)
    outcome = "success" if success else "failure"
    pattern_type = "tool_use_success" if success else "tool_use_failure"
    signature = _signature(tool_name, tool_input, tool_response)

    example = {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_response": {
            "success": tool_response.get("success"),
            "exit_code": tool_response.get("exit_code"),
            "error": tool_response.get("error"),
        },
        "cwd": cwd,
    }

    sm.add_pattern(
        pattern_type=pattern_type,
        signature=signature,
        example=example,
        suggested_fix="Reuse successful signatures; inspect failures for deterministic corrections.",
        verify_cmd=["python3", str(RUNTIME_DIR / "generate_quality_report.py")],
        outcome=outcome,
        meta={"tool_name": tool_name},
    )

    sm.record_event(
        "operation",
        {
            "tool_name": tool_name,
            "success": success,
            "cwd": cwd,
        },
    )

    print(json.dumps({"ok": True, "pattern_type": pattern_type, "signature": signature}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
