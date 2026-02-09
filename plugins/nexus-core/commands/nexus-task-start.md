---
description: Start a NEXUS task (sets current_task.json)
argument-hint: <goal>
allowed-tools: [Bash]
---

# /nexus-task-start

User arguments: $ARGUMENTS

## Your task

1. Read `~/.claude/state/nexus_plugin_runtime.json` to find the installed `nexus-core` plugin root.
2. Start a task using:

```bash
python3 <plugin_root>/nexus_cli.py task start "$ARGUMENTS"
```

3. Print the JSON output only.

