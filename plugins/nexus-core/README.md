# nexus-core (NEXUS) - Claude Code Plugin

Deterministic, hook-driven quality + state scaffold for Claude Code.

## Hooks

### SessionStart
- records session start event
- refreshes mental model scan (throttled)
- injects strict "Codex-grade" additional context
- writes runtime location to: `~/.claude/state/nexus_plugin_runtime.json`

### PreToolUse
- `preflight_gate.py` blocks broken `Write` operations:
  - `.py`: `ast.parse`
  - `.json`: `json.loads`
  - `.toml`: `tomllib.loads`
- `audit_logger.py` writes raw payloads to: `~/.claude/logs/audit.jsonl`

### PostToolUse (order matters)
1. `quality_gate.py` (must be first)
2. `audit_logger.py`
3. `nexus_self_heal.py`
4. `nexus_auto_learn.py`

### SessionEnd
- records session end event
- appends evidence summary to:
  - `~/.claude/logs/sessions.log`
  - `<project>/.claude/memory/session_log.md`

## State

All persistent state lives under `~/.claude/state/`:

- `performance_metrics.json`
- `learning_patterns.json`
- `incidents.jsonl`
- `fix_queue.jsonl`
- `tasks.jsonl`
- `current_task.json`
- `mental_model.json`
- `quality_report.json`

## Cross-Machine State (No Backend Yet)

Export:
```bash
python3 nexus_state_bundle.py export
```

Import (replace mode):
```bash
python3 nexus_state_bundle.py import /path/to/nexus_state_YYYYMMDD_HHMMSS.tar.gz --mode replace
```
