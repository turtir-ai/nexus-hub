---
description: Import a NEXUS state bundle (replace mode) from another machine
argument-hint: <bundle.tar.gz>
allowed-tools: [Bash]
---

# /nexus-import-state

User arguments: $ARGUMENTS

## Your task

1. Read `~/.claude/state/nexus_plugin_runtime.json` to find the installed `nexus-core` plugin root.
2. Import in replace mode:

```bash
python3 <plugin_root>/nexus_state_bundle.py import "$ARGUMENTS" --mode replace
```

3. Print the output only.

