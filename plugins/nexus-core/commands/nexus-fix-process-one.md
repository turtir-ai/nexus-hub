---
description: Process one pending fix task (verification-only; no auto-edits)
allowed-tools: [Bash]
---

# /nexus-fix-process-one

## Your task

1. Read `~/.claude/state/nexus_plugin_runtime.json` to find the installed `nexus-core` plugin root.
2. Run:

```bash
python3 <plugin_root>/nexus_cli.py fix process-one
```

3. Print the JSON output only.

