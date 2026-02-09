#!/usr/bin/env python3
"""NEXUS V3.5.0 self-healing hook: tool failure -> incident -> fix task."""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from _hook_io import get_project_root, read_hook_event

CLAUDE_DIR = pathlib.Path.home() / ".claude"
RUNTIME_DIR = pathlib.Path(os.environ.get("CLAUDE_PLUGIN_ROOT", pathlib.Path(__file__).resolve().parents[1]))
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from state_manager import get_state_manager

try:
    from fix_queue import add_fix_from_incident
except Exception:
    import importlib.util

    spec = importlib.util.spec_from_file_location("fix_queue", RUNTIME_DIR / "hooks" / "fix_queue.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    add_fix_from_incident = module.add_fix_from_incident


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _response_failed(response: Dict[str, Any]) -> bool:
    if not isinstance(response, dict):
        return False

    if response.get("success") is False:
        return True

    exit_code = response.get("exit_code")
    if isinstance(exit_code, int) and exit_code != 0:
        return True

    stderr = str(response.get("stderr", "") or "")
    error = str(response.get("error", "") or "")
    combined = f"{stderr}\n{error}".lower()

    fatal_patterns = [
        "traceback",
        "exception",
        "syntaxerror",
        "permission denied",
        "no such file",
        "not found",
        "modulenotfounderror",
        "fatal",
    ]
    return any(pattern in combined for pattern in fatal_patterns)


def _classify_incident(response: Dict[str, Any]) -> str:
    text = " ".join(
        [
            str(response.get("error", "")),
            str(response.get("stderr", "")),
            str(response.get("stdout", "")),
        ]
    ).lower()

    if "permission denied" in text:
        return "permission_denied"
    if "no such file" in text or "not found" in text:
        return "file_not_found"
    if "modulenotfounderror" in text or re.search(r"\bimporterror\b", text):
        return "import_error"
    if "syntaxerror" in text or "parse" in text:
        return "syntax_error"
    if "timeout" in text:
        return "timeout"
    return "tool_failure"


def _signature_for_incident(kind: str, response: Dict[str, Any]) -> str:
    stderr = str(response.get("stderr", "") or "")
    if kind == "import_error":
        match = re.search(r"No module named ['\"]([^'\"]+)['\"]", stderr)
        if match:
            return f"incident:import:{match.group(1)}"
    return f"incident:{kind}"


def main() -> int:
    event = read_hook_event()
    if not event:
        print("ok: empty_event")
        return 0

    tool_name = event.get("tool_name") or "unknown_tool"
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    tool_response = event.get("tool_response") if isinstance(event.get("tool_response"), dict) else {}
    cwd = str(get_project_root(event))

    if not _response_failed(tool_response):
        print(f"ok: {tool_name} succeeded")
        return 0

    sm = get_state_manager()
    incident_class = _classify_incident(tool_response)
    signature = _signature_for_incident(incident_class, tool_response)

    incident = {
        "id": f"inc_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
        "timestamp": _now_iso(),
        "source": "nexus_self_heal",
        "incident_class": incident_class,
        "signature": signature,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_response": tool_response,
        "cwd": cwd,
        "error": tool_response.get("error") or tool_response.get("stderr") or "tool failure",
        "status": "open",
    }

    sm.record_incident(incident)

    current_confidence = sm.load_msv().get("state_vector", {}).get("confidence", 0.5)
    sm.update_msv(
        {
            "blocked": True,
            "confidence": max(0.0, float(current_confidence) - 0.1),
        }
    )

    sm.add_pattern(
        pattern_type=f"incident:{incident_class}",
        signature=signature,
        example=incident,
        suggested_fix="Review incident, apply deterministic fix, rerun verify_cmd.",
        verify_cmd=["python3", str(RUNTIME_DIR / "nexus_cli.py"), "fix", "process-one"],
        outcome="failure",
        meta={"tool_name": tool_name, "cwd": cwd},
    )

    task_id = add_fix_from_incident(incident)

    print(
        json.dumps(
            {
                "ok": True,
                "incident_id": incident["id"],
                "incident_class": incident_class,
                "fix_task_id": task_id,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
