---
description: Show NEXUS fix queue stats (pending/failed/completed)
allowed-tools: [Bash]
---

# /nexus-fix-stats

## Your task

1. Read `~/.claude/state/nexus_plugin_runtime.json` to find the installed `nexus-core` plugin root.
2. Run:

```bash
python3 <plugin_root>/nexus_cli.py fix stats
```

3. Print the JSON output only.

