#!/usr/bin/env python3
"""NEXUS V3.5.0 state manager with robust metrics and learning storage."""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class NexusStateManager:
    """Manage persistent NEXUS state across sessions."""

    EXAMPLE_LIMIT = 8

    def __init__(self):
        self.state_dir = pathlib.Path.home() / ".claude" / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.msv_file = self.state_dir / "msv.json"
        self.mental_model_file = self.state_dir / "mental_model.json"
        self.learning_file = self.state_dir / "learning_patterns.json"
        self.metrics_file = self.state_dir / "performance_metrics.json"
        self.history_file = self.state_dir / "session_history.jsonl"
        self.incidents_file = self.state_dir / "incidents.jsonl"

    def _load_json(self, path: pathlib.Path, default_factory):
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                return default_factory()
        return default_factory()

    def _save_json(self, path: pathlib.Path, data: Dict[str, Any]):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def load_msv(self) -> Dict[str, Any]:
        return self._load_json(self.msv_file, self._init_msv)

    def save_msv(self, msv: Dict[str, Any]):
        msv.setdefault("version", "3.5.0")
        msv["last_updated"] = _now_iso()
        self._save_json(self.msv_file, msv)

    def update_msv(self, updates: Dict[str, Any]):
        msv = self.load_msv()
        state_vector = msv.setdefault("state_vector", {})
        for key, value in updates.items():
            state_vector[key] = value
        self.save_msv(msv)

    def load_mental_model(self) -> Dict[str, Any]:
        return self._load_json(self.mental_model_file, self._init_mental_model)

    def save_mental_model(self, model: Dict[str, Any]):
        model.setdefault("version", "3.5.0")
        model["last_updated"] = _now_iso()
        self._save_json(self.mental_model_file, model)

    def load_learning(self) -> Dict[str, Any]:
        learning = self._load_json(self.learning_file, self._init_learning)
        normalized, changed = self._normalize_learning(learning)
        if changed:
            self.save_learning(normalized)
        return normalized

    def save_learning(self, learning: Dict[str, Any]):
        learning.setdefault("version", "3.5.0")
        learning["last_updated"] = _now_iso()
        self._save_json(self.learning_file, learning)

    def _ensure_signature_entry(
        self,
        learning: Dict[str, Any],
        pattern_type: str,
        signature: str,
    ) -> Dict[str, Any]:
        patterns = learning.setdefault("patterns", {})
        type_bucket = patterns.setdefault(
            pattern_type,
            {
                "total_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "last_seen": None,
                "by_signature": {},
            },
        )
        sig_bucket = type_bucket.setdefault("by_signature", {}).setdefault(
            signature,
            {
                "count": 0,
                "success_count": 0,
                "failure_count": 0,
                "last_seen": None,
                "examples": [],
                "suggested_fix": "",
                "verify_cmd": [],
                "meta": {},
            },
        )
        return sig_bucket

    def _normalize_learning(self, learning: Dict[str, Any]):
        changed = False
        patterns = learning.get("patterns")

        if not isinstance(patterns, dict):
            learning = self._init_learning()
            return learning, True

        # Detect already-normalized structure.
        already_normalized = True
        for value in patterns.values():
            if not isinstance(value, dict) or "by_signature" not in value:
                already_normalized = False
                break
        if already_normalized:
            return learning, False

        normalized = self._init_learning()

        for pattern_type, items in patterns.items():
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    signature = (
                        str(
                            item.get("signature")
                            or item.get("error")
                            or item.get("command")
                            or item.get("type")
                            or pattern_type
                        )
                        .strip()
                        .replace("\n", " ")
                    )
                    outcome = str(item.get("outcome", "unknown")).lower()
                    self._add_pattern_internal(
                        normalized,
                        pattern_type=pattern_type,
                        signature=signature,
                        example=item,
                        suggested_fix=item.get("suggested_fix", ""),
                        verify_cmd=item.get("verify_cmd", []),
                        outcome=outcome,
                        meta=item.get("meta", {}),
                        timestamp=item.get("timestamp"),
                    )
                    changed = True
            elif isinstance(items, dict):
                signature = str(pattern_type)
                self._add_pattern_internal(
                    normalized,
                    pattern_type=pattern_type,
                    signature=signature,
                    example=items,
                    suggested_fix=items.get("suggested_fix", ""),
                    verify_cmd=items.get("verify_cmd", []),
                    outcome=items.get("outcome", "unknown"),
                    meta=items.get("meta", {}),
                    timestamp=items.get("timestamp"),
                )
                changed = True

        if not changed:
            normalized = learning
        return normalized, changed

    def _add_pattern_internal(
        self,
        learning: Dict[str, Any],
        pattern_type: str,
        signature: str,
        example: Optional[Dict[str, Any]],
        suggested_fix: str,
        verify_cmd: Optional[List[str]],
        outcome: str,
        meta: Optional[Dict[str, Any]],
        timestamp: Optional[str] = None,
    ):
        safe_type = str(pattern_type or "unknown").strip() or "unknown"
        safe_signature = str(signature or "unknown").strip().replace("\n", " ")
        ts = timestamp or _now_iso()

        patterns = learning.setdefault("patterns", {})
        type_bucket = patterns.setdefault(
            safe_type,
            {
                "total_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "last_seen": None,
                "by_signature": {},
            },
        )
        sig_bucket = type_bucket.setdefault("by_signature", {}).setdefault(
            safe_signature,
            {
                "count": 0,
                "success_count": 0,
                "failure_count": 0,
                "last_seen": None,
                "examples": [],
                "suggested_fix": "",
                "verify_cmd": [],
                "meta": {},
            },
        )

        type_bucket["total_count"] += 1
        type_bucket["last_seen"] = ts
        sig_bucket["count"] += 1
        sig_bucket["last_seen"] = ts

        outcome_norm = str(outcome or "unknown").lower()
        if outcome_norm == "success":
            type_bucket["success_count"] += 1
            sig_bucket["success_count"] += 1
        elif outcome_norm == "failure":
            type_bucket["failure_count"] += 1
            sig_bucket["failure_count"] += 1

        if suggested_fix:
            sig_bucket["suggested_fix"] = str(suggested_fix)
        if isinstance(verify_cmd, list) and verify_cmd:
            sig_bucket["verify_cmd"] = verify_cmd
        if isinstance(meta, dict) and meta:
            sig_bucket["meta"] = meta

        if example is not None:
            sample = {
                "timestamp": ts,
                "outcome": outcome_norm,
                "example": example,
            }
            examples = sig_bucket.setdefault("examples", [])
            examples.append(sample)
            if len(examples) > self.EXAMPLE_LIMIT:
                del examples[:-self.EXAMPLE_LIMIT]

    def add_pattern(
        self,
        pattern_type: str,
        signature: Any = None,
        example: Optional[Dict[str, Any]] = None,
        suggested_fix: str = "",
        verify_cmd: Optional[List[str]] = None,
        outcome: str = "unknown",
        meta: Optional[Dict[str, Any]] = None,
    ):
        """
        Add or update a learning pattern.

        Backward compatibility:
          add_pattern(pattern_type, { ...legacy dict... })
        """
        # Legacy call style: add_pattern("type", { ... })
        if isinstance(signature, dict) and example is None:
            legacy = signature
            signature = (
                legacy.get("signature")
                or legacy.get("error")
                or legacy.get("command")
                or legacy.get("type")
                or pattern_type
            )
            example = legacy
            suggested_fix = legacy.get("suggested_fix", suggested_fix)
            verify_cmd = legacy.get("verify_cmd", verify_cmd)
            outcome = legacy.get("outcome", outcome)
            meta = legacy.get("meta", meta)

        learning = self.load_learning()
        self._add_pattern_internal(
            learning,
            pattern_type=pattern_type,
            signature=str(signature or pattern_type),
            example=example,
            suggested_fix=suggested_fix,
            verify_cmd=verify_cmd,
            outcome=outcome,
            meta=meta,
        )
        self.save_learning(learning)

    def _metrics_defaults(self) -> Dict[str, Any]:
        return {
            "version": "3.5.0",
            "created": _now_iso(),
            "last_updated": _now_iso(),
            "session_count": 0,
            "tasks_completed": 0,
            "tasks_successful": 0,
            "tasks_failed": 0,
            "task_progress_events": 0,
            "avg_duration_seconds": 0,
            "success_rate": 0.0,
            "incidents_total": 0,
            "incidents_open": 0,
            "fixes_completed": 0,
            "fixes_failed": 0,
            "mean_time_to_close_task": None,
            "mean_time_to_verify_fix": None,
            "auto_fix_attempted": 0,
            "auto_fix_success": 0,
            "manual_interventions": 0,
            "mean_time_to_fix_sec": None,
            "runs": 0,
            "rollback_count": 0,
            "last_failed_check": None,
            "last_result": {},
            "last_run": None,
            "agent_performance": {
                "pilot": {"tasks": 0, "success_rate": 0},
                "guardian": {"alerts": 0, "prevented": 0},
                "healer": {"fixes": 0, "success_rate": 0},
                "discover": {"scans": 0, "patterns_found": 0},
            },
        }

    def _with_metric_defaults(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        defaults = self._metrics_defaults()
        for key, value in defaults.items():
            if key not in metrics:
                metrics[key] = value
        if "agent_performance" not in metrics or not isinstance(metrics["agent_performance"], dict):
            metrics["agent_performance"] = defaults["agent_performance"]
        else:
            for agent, vals in defaults["agent_performance"].items():
                if agent not in metrics["agent_performance"]:
                    metrics["agent_performance"][agent] = vals
                else:
                    for sub_key, sub_value in vals.items():
                        metrics["agent_performance"][agent].setdefault(sub_key, sub_value)

        tasks_completed = int(metrics.get("tasks_completed", 0) or 0)
        tasks_successful = int(metrics.get("tasks_successful", 0) or 0)
        metrics["success_rate"] = round((tasks_successful / tasks_completed), 4) if tasks_completed else 0.0
        return metrics

    def load_metrics(self) -> Dict[str, Any]:
        metrics = self._load_json(self.metrics_file, self._metrics_defaults)
        normalized = self._with_metric_defaults(metrics)
        return normalized

    def save_metrics(self, metrics: Dict[str, Any]):
        normalized = self._with_metric_defaults(metrics)
        normalized["last_updated"] = _now_iso()
        self._save_json(self.metrics_file, normalized)

    def record_event(self, event_type: str, data: Dict[str, Any]):
        event = {
            "timestamp": _now_iso(),
            "type": event_type,
            "data": data,
        }
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        with self.history_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def get_session_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        if not self.history_file.exists():
            return []
        lines = self.history_file.read_text().splitlines()
        result = []
        for line in lines[-limit:]:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return result

    def record_incident(self, incident: Dict[str, Any]):
        self.incidents_file.parent.mkdir(parents=True, exist_ok=True)
        with self.incidents_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(incident, ensure_ascii=False, default=str) + "\n")

        metrics = self.load_metrics()
        metrics["incidents_total"] = int(metrics.get("incidents_total", 0)) + 1
        metrics["incidents_open"] = int(metrics.get("incidents_open", 0)) + 1
        self.save_metrics(metrics)

    def record_fix_verification(self, success: bool, duration_seconds: float):
        metrics = self.load_metrics()
        key = "fixes_completed" if success else "fixes_failed"
        metrics[key] = int(metrics.get(key, 0)) + 1

        current_mean = metrics.get("mean_time_to_verify_fix")
        total = int(metrics.get("fixes_completed", 0)) + int(metrics.get("fixes_failed", 0))
        if current_mean is None or total <= 1:
            metrics["mean_time_to_verify_fix"] = round(float(duration_seconds), 4)
        else:
            metrics["mean_time_to_verify_fix"] = round(
                ((float(current_mean) * (total - 1)) + float(duration_seconds)) / total,
                4,
            )

        if success:
            metrics["incidents_open"] = max(0, int(metrics.get("incidents_open", 0)) - 1)

        self.save_metrics(metrics)

    def record_task_close(self, success: bool, duration_seconds: float):
        metrics = self.load_metrics()
        metrics["tasks_completed"] = int(metrics.get("tasks_completed", 0)) + 1
        if success:
            metrics["tasks_successful"] = int(metrics.get("tasks_successful", 0)) + 1
        else:
            metrics["tasks_failed"] = int(metrics.get("tasks_failed", 0)) + 1

        current_mean = metrics.get("mean_time_to_close_task")
        total = int(metrics.get("tasks_completed", 0))
        if current_mean is None or total <= 1:
            metrics["mean_time_to_close_task"] = round(float(duration_seconds), 4)
        else:
            metrics["mean_time_to_close_task"] = round(
                ((float(current_mean) * (total - 1)) + float(duration_seconds)) / total,
                4,
            )

        self.save_metrics(metrics)

    def _init_msv(self) -> Dict[str, Any]:
        return {
            "version": "3.5.0",
            "created": _now_iso(),
            "last_updated": _now_iso(),
            "state_vector": {
                "confidence": 0.5,
                "progress": 0.0,
                "blocked": False,
                "learning_rate": 0.1,
                "resource_utilization": 0.0,
            },
            "context": {
                "current_project": str(pathlib.Path.cwd()),
                "active_task": None,
                "agent_status": {
                    "nexus": "active",
                    "pilot": "idle",
                    "guardian": "monitoring",
                    "healer": "idle",
                    "discover": "idle",
                },
            },
            "patterns": {
                "successful_approaches": [],
                "failed_approaches": [],
                "user_preferences": {},
            },
        }

    def _init_mental_model(self) -> Dict[str, Any]:
        return {
            "version": "3.5.0",
            "created": _now_iso(),
            "last_updated": _now_iso(),
            "projects": {},
            "current_project": str(pathlib.Path.cwd()),
            "architecture_patterns": [],
            "dependency_graph": {},
            "known_issues": [],
            "last_scan": None,
        }

    def _init_learning(self) -> Dict[str, Any]:
        return {
            "version": "3.5.0",
            "created": _now_iso(),
            "last_updated": _now_iso(),
            "patterns": {},
            "insights": [],
        }


_state_manager = None


def get_state_manager() -> NexusStateManager:
    global _state_manager
    if _state_manager is None:
        _state_manager = NexusStateManager()
    return _state_manager


if __name__ == "__main__":
    sm = NexusStateManager()
    sm.save_msv(sm.load_msv())
    sm.save_mental_model(sm.load_mental_model())
    sm.save_learning(sm.load_learning())
    sm.save_metrics(sm.load_metrics())
    print(f"State directory: {sm.state_dir}")
    print("NEXUS V3.5.0 state initialized")
