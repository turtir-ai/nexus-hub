---
description: Export a safe NEXUS state bundle (tar.gz) for moving to another machine
allowed-tools: [Bash]
---

# /nexus-export-state

## Your task

1. Read `~/.claude/state/nexus_plugin_runtime.json` to find the installed `nexus-core` plugin root.
2. Run:

```bash
python3 <plugin_root>/nexus_state_bundle.py export
```

3. Print the output only.

