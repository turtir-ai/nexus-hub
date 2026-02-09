#!/usr/bin/env python3
"""NEXUS V3.5.0 quality report generator."""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any, Dict

CLAUDE_DIR = pathlib.Path.home() / ".claude"
STATE_DIR = CLAUDE_DIR / "state"
METRICS = STATE_DIR / "performance_metrics.json"
MENTAL_MODEL = STATE_DIR / "mental_model.json"
MSV = STATE_DIR / "msv.json"
LEARNING = STATE_DIR / "learning_patterns.json"
FIX_QUEUE = STATE_DIR / "fix_queue.jsonl"
INCIDENTS = STATE_DIR / "incidents.jsonl"
TASKS = STATE_DIR / "tasks.jsonl"
MSG_LOG = STATE_DIR / "agent_messages.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _count_jsonl(path: pathlib.Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def _count_patterns(learning: Dict[str, Any]) -> int:
    patterns = learning.get("patterns", {})
    if not isinstance(patterns, dict):
        return 0

    total = 0
    for value in patterns.values():
        if isinstance(value, dict) and "by_signature" in value:
            for signature in value.get("by_signature", {}).values():
                if isinstance(signature, dict):
                    total += int(signature.get("count", 0))
        elif isinstance(value, list):
            total += len(value)
        elif isinstance(value, dict):
            total += 1
    return total


def get_assessment(score: int) -> str:
    if score >= 90:
        return "Expert autonomous agent"
    if score >= 75:
        return "Advanced autonomous system"
    if score >= 60:
        return "Intermediate agentic framework"
    if score >= 40:
        return "Basic agent scaffolding"
    return "Prototype only"


def get_priorities(evidence: Dict[str, Any]) -> list:
    priorities = []
    if evidence.get("pattern_learning", {}).get("points", 0) == 0:
        priorities.append(
            {
                "priority": "CRITICAL",
                "item": "Enable Pattern Learning",
                "actions": ["Record patterns from quality gate/self-heal/fix queue"],
            }
        )
    if evidence.get("task_execution", {}).get("points", 0) == 0:
        priorities.append(
            {
                "priority": "HIGH",
                "item": "Track Task Lifecycle",
                "actions": ["Use nexus task start/close and update metrics"],
            }
        )
    if evidence.get("self_healing", {}).get("points", 0) == 0:
        priorities.append(
            {
                "priority": "HIGH",
                "item": "Process Incidents",
                "actions": ["Generate incidents and run fix verification loop"],
            }
        )
    return priorities


def main() -> None:
    metrics = _load_json(METRICS)
    msv = _load_json(MSV)
    mental_model = _load_json(MENTAL_MODEL)
    learning = _load_json(LEARNING)

    total_patterns = _count_patterns(learning)
    msg_count = _count_jsonl(MSG_LOG)
    fix_tasks = _count_jsonl(FIX_QUEUE)
    incident_log_count = _count_jsonl(INCIDENTS)
    task_events = _count_jsonl(TASKS)

    score = 0
    evidence: Dict[str, Any] = {}

    # State persistence (20)
    if MSV.exists() and MENTAL_MODEL.exists():
        score += 20
        evidence["state_persistence"] = {
            "points": 20,
            "confidence": msv.get("state_vector", {}).get("confidence", 0),
            "project": mental_model.get("current_project"),
        }
    else:
        evidence["state_persistence"] = {"points": 0, "note": "Missing MSV or mental model"}

    # Pattern learning (20)
    if total_patterns > 0:
        score += 20
        evidence["pattern_learning"] = {
            "points": 20,
            "total_patterns": total_patterns,
            "pattern_types": len(learning.get("patterns", {})) if isinstance(learning.get("patterns", {}), dict) else 0,
        }
    else:
        evidence["pattern_learning"] = {"points": 0, "note": "No patterns learned"}

    # Agent communication (15)
    if msg_count > 0:
        score += 15
        evidence["agent_communication"] = {"points": 15, "message_count": msg_count}
    else:
        evidence["agent_communication"] = {"points": 0, "note": "No agent messages"}

    # Self-healing (10)
    incidents_total = int(metrics.get("incidents_total", 0) or 0)
    fixes_completed = int(metrics.get("fixes_completed", 0) or 0)
    fixes_failed = int(metrics.get("fixes_failed", 0) or 0)
    if incidents_total > 0 and (fixes_completed + fixes_failed) > 0:
        score += 10
        evidence["self_healing"] = {
            "points": 10,
            "incidents_total": incidents_total,
            "incidents_logged": incident_log_count,
            "fixes_completed": fixes_completed,
            "fixes_failed": fixes_failed,
        }
    elif incidents_total > 0:
        score += 5
        evidence["self_healing"] = {
            "points": 5,
            "incidents_total": incidents_total,
            "incidents_logged": incident_log_count,
            "note": "Incidents logged; verify loop not exercised",
        }
    else:
        evidence["self_healing"] = {"points": 0, "note": "No incidents"}

    # Task execution (15)
    tasks_completed = int(metrics.get("tasks_completed", 0) or 0)
    if tasks_completed > 0:
        score += 15
        evidence["task_execution"] = {
            "points": 15,
            "tasks_completed": tasks_completed,
            "tasks_successful": int(metrics.get("tasks_successful", 0) or 0),
            "tasks_failed": int(metrics.get("tasks_failed", 0) or 0),
            "task_events": task_events,
        }
    else:
        evidence["task_execution"] = {"points": 0, "note": "No completed tasks"}

    # Quality gate (20)
    runs = int(metrics.get("runs", 0) or 0)
    rollbacks = int(metrics.get("rollback_count", 0) or 0)
    if runs > 0:
        score += 20
        evidence["quality_gate"] = {
            "points": 20,
            "runs": runs,
            "rollbacks": rollbacks,
            "last_failed_check": metrics.get("last_failed_check"),
        }
    else:
        evidence["quality_gate"] = {"points": 0, "note": "No quality gate runs"}

    report = {
        "timestamp": _now_iso(),
        "version": "3.5.0",
        "quality_score": score,
        "max_score": 100,
        "percentage": round((score / 100) * 100, 1),
        "evidence": evidence,
        "metrics": {
            "runs": runs,
            "rollbacks": rollbacks,
            "incidents_total": incidents_total,
            "fixes_completed": fixes_completed,
            "fixes_failed": fixes_failed,
            "tasks_completed": tasks_completed,
            "patterns": total_patterns,
            "messages": msg_count,
            "fix_tasks": fix_tasks,
        },
        "assessment": get_assessment(score),
        "next_priorities": get_priorities(evidence),
    }

    # Keep both outputs for compatibility.
    (STATE_DIR / "quality_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    (CLAUDE_DIR / "quality_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
