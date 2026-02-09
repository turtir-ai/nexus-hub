---
name: nexus-workflow
description: Use when the user asks how NEXUS works, how to use task tracking/fix queue/pattern learning, how to migrate to another machine, or how to debug why hooks are not firing. Provides an evidence-first operating procedure.
tools: Read, Glob, Grep, Bash
---

# NEXUS Workflow (Plugin Mode)

NEXUS is not a daemon. It is a **hook-driven runtime scaffold** for Claude Code.

## What NEXUS Does (Practical)

- **PreToolUse**:
  - `preflight_gate.py` blocks obviously broken writes (Python/JSON/TOML parse errors).
  - `audit_logger.py` logs the event payload.
- **PostToolUse**:
  - `quality_gate.py` runs deterministic checks and can rollback on failure.
  - `nexus_self_heal.py` records incidents on tool failures and creates fix tasks.
  - `nexus_auto_learn.py` increments learning patterns per signature/outcome.
- **SessionStart/End**:
  - Records session events, refreshes mental model scan (throttled),
    and injects a strict \"Codex-grade\" context for better output quality.

All state is stored under: `~/.claude/state/`

## Quick Health Check

1. Validate the plugin (on the machine where the marketplace repo exists):
```bash
claude plugin validate /path/to/nexus-hub/plugins/nexus-core
```

2. Check NEXUS state is being written:
```bash
ls -la ~/.claude/state
```

3. Generate a quality report (if the CLI is available in your environment):
```bash
python3 ~/.claude/generate_quality_report.py || true
cat ~/.claude/state/quality_report.json || true
```

## Cross-Machine (No Cloud Yet)

Use the state bundle export/import:
```bash
# export
python3 <nexus-core-root>/nexus_state_bundle.py export

# import (replace mode)
python3 <nexus-core-root>/nexus_state_bundle.py import /path/to/bundle.tar.gz
```

The plugin writes its runtime location here to help commands find it:
- `~/.claude/state/nexus_plugin_runtime.json`

## Debugging Why Hooks Don't Fire

- Ensure the plugin is enabled:
```bash
claude plugin list
```

- Ensure you are not double-running hooks from `~/.claude/settings.json` (legacy).
- Use `~/.claude/logs/audit.jsonl` to confirm hook events are being received.
