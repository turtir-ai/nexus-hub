# NEXUS HUB (Next) - Device-Sync Memory + Skills/MCP via Claude Code Plugins

## Why This Exists
You already have a working local core:
- deterministic hooks (quality gate, self-heal, fix queue, task metrics, pattern learning)
- local state under `~/.claude/state`

The gap is portability and cross-device continuity.

This project focuses on:
1) packaging your NEXUS core as a **Claude Code plugin** (so any machine can install it consistently)
2) adding a **sync layer** later (membership + DB) without breaking the local/offline workflow

## Ground Truth (Claude Code Capability Model)
Claude Code supports:
- Hook scripts (PreToolUse/PostToolUse etc.) configured in settings
- A first-class **plugin** system (plugins can ship hooks, skills, commands, and MCP servers)
- A plugin marketplace mechanism (install/update via configured marketplaces)
- MCP server configuration via JSON files

So: do not invent a new plugin loader unless you're targeting non-Claude environments.

## Phase 1 (MVP): "NEXUS-as-a-Plugin"
Deliverable: a plugin repo folder that can be installed locally and produces the same behavior as your current `~/.claude/hooks/*` setup.

### Proposed plugin structure
plugin/
  .claude-plugin/
    plugin.json
  hooks/
    quality_gate.py
    nexus_self_heal.py
    nexus_auto_learn.py
    fix_queue.py
    _hook_io.py
  skills/
    nexus_quality/
      SKILL.md
  commands/
    nexus_status.py
    nexus_fix_process_one.py
  mcp/
    .mcp.json (optional)

### Requirements
- No hard-coded paths (use HOME + project cwd from hook event JSON).
- Hooks must never crash on missing keys (store raw payload).
- "Finding" outputs must be evidence-based (no HTTP-200-only conclusions).

## Phase 2 (MVP+): Sync-Ready Event Log (Offline First)
Before building a backend, normalize local state into an append-only event log:

core/
  events/
    writer.py  (append JSONL)
    schema.py  (canonical event fields)
    reducer.py (derive metrics/patterns/fix queue)

Rationale: syncing raw events is easier than syncing derived state.

## Phase 3 (Later): Membership + Cross-Device Sync
services/
  api/    (auth + sync endpoints)
  db/     (postgres schema migrations)

Start with:
- email login
- device_id
- push/pull events by cursor

Privacy:
- never upload full file contents by default
- store hashes + summaries + metrics

## Immediate Next Task (This Week)
1) Create `plugin/` scaffolding and a minimal `plugin.json`.
2) Port the existing hook scripts into `plugin/hooks/` without behavior changes.
3) Add "evidence gate" checks to prevent false positives in any security validation output.
4) Add a small test harness under `plugin/tests/` that pipes sample hook JSON into scripts.
5) Write `plugin/README.md` with install steps (macOS focused).
