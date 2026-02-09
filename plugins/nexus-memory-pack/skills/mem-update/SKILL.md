---
name: mem-update
description: Update memory banks with new learnings, error patterns, or context
disable-model-invocation: true
---

## Usage

```
/mem-update <global|project> "<section>" "<content>"
```

## Examples

```
# Update global memory
/mem-update global "## 🚨 ERROR PATTERNS" "Write tool missing file_path - Always include file_path parameter"

# Update project memory
/mem-update project "## 🧪 NEW TESTS" "RT-016: Advanced SQL Injection - Status: Pending"
```

## What it does

1. Identifies correct memory file (global or project)
2. Finds or creates specified section
3. Appends content with timestamp
4. Maintains consistent formatting

## Memory files

- Global: `~/.claude/memory_bank.md`
- Project (current repo): `./.claude/memory/MEMORY.md`
- Project updates (optional): `./.claude/memory/MEMORY_UPDATE.md`

## When to update

- New error patterns discovered
- User preferences learned
- Project milestones reached
- Solutions that worked (or didn't)
- Important context for future sessions

## Format

```markdown
### [Entry Name] (2026-02-06)
- **Context:** What were you doing
- **Finding:** What you learned
- **Action:** What to do next time
```

## Preferred (Portable) Write Method

Avoid embedding huge heredocs in Claude Code permission settings. Prefer one of:

```bash
# Global memory (hot): write a short note (auto-keeps memory_bank small)
python3 ~/.claude/nexus_mem.py remember --scope global --category learning --tags "nexus,quality" --refs "path/to/file.py" "Short summary + verify cmd"

# Project memory (cold): keep details inside the repo
python3 ~/.claude/nexus_mem.py remember --scope project --category learning --tags "bugfix" --refs "src/app.py" "Detailed notes for this repo"
```

## Portable Memory (Export/Import)

Move memory to another computer without bloating the hot memory bank:

```bash
# Export a bundle (tar.gz)
python3 ~/.claude/nexus_mem.py export --out ~/Downloads/nexus_memory.tar.gz

# Import on another machine (merges notes; overwrites pinned if requested)
python3 ~/.claude/nexus_mem.py import --overwrite-pinned ~/Downloads/nexus_memory.tar.gz
```
