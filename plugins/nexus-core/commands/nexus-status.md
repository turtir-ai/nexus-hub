---
description: Show NEXUS status (current task, metrics, fix queue)
allowed-tools: Bash(python3:*), Bash(cat:*), Bash(ls:*)
---

## Context

- Plugin runtime info: !`cat ~/.claude/state/nexus_plugin_runtime.json 2>/dev/null || echo "(missing: nexus_plugin_runtime.json)"`
- NEXUS state dir: !`ls -la ~/.claude/state 2>/dev/null | head -50`

## Your task

1. Determine the installed `nexus-core` plugin root from `~/.claude/state/nexus_plugin_runtime.json`.
2. Run:
   - `python3 <plugin_root>/nexus_cli.py status`
3. Print the JSON output only.

