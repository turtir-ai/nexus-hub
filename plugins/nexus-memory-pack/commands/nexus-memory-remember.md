---
description: Add a global memory note (writes notes.jsonl + rebuilds memory_bank)
argument-hint: <note>
allowed-tools: [Bash]
---

# /nexus-memory-remember

User arguments: $ARGUMENTS

## Your task

1. Run:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/nexus_mem.py remember --scope global --category learning "$ARGUMENTS"
```
2. Print the JSON output only.

