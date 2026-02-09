#!/usr/bin/env python3
"""PreToolUse preflight gate for Write operations.

Goal: catch deterministic parse errors *before* a broken file is written.
This is intentionally conservative to avoid false positives:
- Only runs on tool_name == "Write"
- Only validates full file content (tool_input.content)
- stdlib only

Blocking behavior:
- exit code 2 blocks the tool execution (Claude Code convention)
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from _hook_io import read_hook_event


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def main() -> int:
    event = read_hook_event()
    tool_name = str(event.get("tool_name") or "")
    if tool_name != "Write":
        return 0

    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    file_path = str(tool_input.get("file_path") or tool_input.get("path") or "")
    content = tool_input.get("content")

    if not file_path or not isinstance(content, str):
        return 0

    suffix = Path(file_path).suffix.lower()

    if suffix == ".py":
        try:
            ast.parse(content, filename=file_path)
        except SyntaxError as exc:
            loc = f"{exc.lineno}:{exc.offset}" if exc.lineno else ""
            _fail(f"NEXUS preflight blocked Write: Python SyntaxError in {file_path}{(':' + loc) if loc else ''}: {exc.msg}")
        return 0

    if suffix == ".json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            _fail(
                f"NEXUS preflight blocked Write: invalid JSON in {file_path} (line {exc.lineno}, col {exc.colno}): {exc.msg}"
            )
        return 0

    if suffix == ".toml":
        try:
            import tomllib  # py>=3.11

            tomllib.loads(content)
        except Exception as exc:
            _fail(f"NEXUS preflight blocked Write: invalid TOML in {file_path}: {exc}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

