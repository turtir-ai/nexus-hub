---
name: mem-search
description: Search global and project memory banks for context before starting tasks
---

## Usage

```
/mem-search <keyword>
```

## What it does

1. Searches `~/.claude/memory_bank.md` for keyword
2. Searches project memory (current repo): `./.claude/memory/` for keyword (if present)
3. Searches archives: `~/.claude/memory/archives/` for keyword (if present)
3. Returns relevant context from both sources
4. Summarizes findings with file references

## When to use

- Before starting new tasks
- When you need context from previous sessions
- To find error patterns and solutions
- To recall user preferences
- To find project-specific rules

## Search pattern

```bash
# Preferred (portable): search all memory layers
python3 ~/.claude/nexus_mem.py search "<keyword>" | head -120

# Global memory
rg "<keyword>" ~/.claude/memory_bank.md -C 3

# Project memory (current directory)
rg "<keyword>" ./.claude/memory/ -C 3

# Archives (rotated memory bank snapshots)
rg "<keyword>" ~/.claude/memory/archives/ -C 3

# NEXUS state (patterns/incidents/tasks) if you want evidence
rg "<keyword>" ~/.claude/state/{learning_patterns.json,incidents.jsonl,fix_queue.jsonl,tasks.jsonl,session_history.jsonl} -C 2

# All (fastest wide search)
rg "<keyword>" ~/.claude/memory_bank.md ~/.claude/memory/archives/ ./.claude/memory/ ~/.claude/state/ -S -C 2
```

## Output format

```
=== MEMORY SEARCH RESULTS: <keyword> ===

📁 Global Memory:
- [Relevant entries with line numbers]

📁 Project Memory:
- [Relevant entries with file references]

💡 Summary:
- [Key insights found]
```
