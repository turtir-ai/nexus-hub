# NEXUS Memory Pack (Claude Code Plugin)

This plugin upgrades Claude Code memory to be **portable, evidence-friendly, and non-bloated**.

## What It Does

- Keeps `~/.claude/memory_bank.md` small (hot prompt memory)
- Stores long-term notes in `~/.claude/memory/notes.jsonl` (cold memory, append-only)
- Rotates oversized `memory_bank.md` into `~/.claude/memory/archives/` and updates `INDEX.md`
- Provides deterministic search across:
  - `memory_bank.md`, `pinned.md`, `notes.jsonl`, archives
  - NEXUS state (`~/.claude/state/*.json*`)
  - ReMe memory v2 (`~/.claude/memory_v2/*.json`)
  - Project memory (`./.claude/memory/`)

## Files Created/Used

- `~/.claude/memory/pinned.md`
  - Your "pinned" context. Edit this instead of stuffing `memory_bank.md`.
- `~/.claude/memory/notes.jsonl`
  - Append-only memory entries with tags/refs.
- `~/.claude/memory/archives/INDEX.md`
  - Archive index (snapshots of oversized `memory_bank.md`).

## Hooks

- **PostToolUse**: runs `nexus_mem.py remember-hook --no-rebuild` and appends a short `tool_error` note when a tool fails.
- **SessionEnd**: runs `nexus_mem.py rotate` to keep `memory_bank.md` compact.

## Commands

- `nexus-memory-stats`
- `nexus-memory-search`
- `nexus-memory-remember`
- `nexus-memory-rotate`
- `nexus-memory-export`
- `nexus-memory-import`

## Safety

Do not store secrets in memory:
- `.env`, `*.pem`, `*.key`, tokens, credentials
