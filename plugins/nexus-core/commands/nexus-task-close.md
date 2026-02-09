---
description: Close the current NEXUS task (success/fail + optional note)
argument-hint: --success|--fail [--note "..."]
allowed-tools: [Bash]
---

# /nexus-task-close

User arguments: $ARGUMENTS

## Your task

1. Read `~/.claude/state/nexus_plugin_runtime.json` to find the installed `nexus-core` plugin root.
2. Close the active task by passing arguments through:

```bash
python3 <plugin_root>/nexus_cli.py task close $ARGUMENTS
```

3. Print the JSON output only.

