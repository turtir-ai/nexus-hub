---
description: Search memory (memory_bank + archives + notes + state + project memory)
argument-hint: <query>
allowed-tools: [Bash]
---

# /nexus-memory-search

User arguments: $ARGUMENTS

## Your task

1. Run:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/nexus_mem.py search "$ARGUMENTS" --max-results 120
```
2. Print the JSON output only.

