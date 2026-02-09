# NEXUS Hub (Claude Code Local Marketplace)

I built this repo so I can clone it on any machine and get the same NEXUS behavior inside Claude Code.

It is a **local Claude Code plugin marketplace** that ships NEXUS as a real plugin (no hard-coded `/Users/...` paths).

## What You Get

### `nexus-core` plugin (v0.2.0)

Hook-driven, deterministic scaffolding:

- **SessionStart**
  - records a session event + plugin runtime location
  - refreshes a lightweight mental-model scan (throttled)
  - injects a strict “Codex-grade” additional context to reduce weak-model drift
- **PreToolUse**
  - `preflight_gate.py` blocks obviously broken `Write` operations (`.py`/`.json`/`.toml` parse failures)
  - `audit_logger.py` logs raw hook payloads for debugging/evidence
- **PostToolUse** (order matters)
  1. `quality_gate.py` (must run first; can rollback on failure)
  2. `audit_logger.py`
  3. `nexus_self_heal.py` (tool failure -> incident -> fix task)
  4. `nexus_auto_learn.py` (pattern learning)

State is stored under `~/.claude/state/`.

## Install (New Machine)

### 1) Clone
```bash
git clone https://github.com/turtir-ai/nexus-hub.git
cd nexus-hub
```

### 2) Add Marketplace + Install Plugin
```bash
claude plugin marketplace add "$(pwd)"
claude plugin install nexus-core@turtir-ai
claude plugin list
```

### 3) Avoid Double-Running Hooks (Important)
If you have legacy hooks in `~/.claude/settings.json`, keep **one** source of truth:

- Recommended: plugin-only (portable)
- Legacy: settings-driven (not portable)

In plugin-only mode, set:
```bash
jq '.hooks = {}' ~/.claude/settings.json > ~/.claude/settings.json.tmp && mv ~/.claude/settings.json.tmp ~/.claude/settings.json
```

### 4) Restart Claude Code
Claude Code plugin updates and hook registration require a restart to fully apply.

## Verify It’s Working

### Plugin Validation
```bash
claude plugin validate ./plugins/nexus-core
```

### Runtime Proof: Plugin Root File
After a Claude Code session starts, this file should exist:
```bash
cat ~/.claude/state/nexus_plugin_runtime.json
```

### Generate a Quality Report (Plugin-local)
```bash
PLUGIN_ROOT="$(python3 -c 'import json,pathlib; p=pathlib.Path.home()/\".claude/state/nexus_plugin_runtime.json\"; d=json.loads(p.read_text()); print(d[\"nexus-core\"][\"root\"])')"
python3 "$PLUGIN_ROOT/generate_quality_report.py"
cat ~/.claude/state/quality_report.json
```

## Built-In Slash Commands (From The Plugin)

Once installed, these are available inside Claude Code:

- `/nexus-status`
- `/nexus-task-start <goal>`
- `/nexus-task-close --success|--fail [--note "..."]`
- `/nexus-fix-stats`
- `/nexus-fix-process-one`
- `/nexus-export-state`
- `/nexus-import-state <bundle.tar.gz>`

## Cross-Machine Memory (MVP, No DB)

Until the membership/database sync exists, use a deterministic state bundle:

```bash
# export
python3 ./plugins/nexus-core/nexus_state_bundle.py export
```

Copy the generated `.tar.gz` to the other machine, then:

```bash
# import (replace mode)
python3 ./plugins/nexus-core/nexus_state_bundle.py import /path/to/bundle.tar.gz --mode replace
```

## Extending The Hub

- Add new plugins under `plugins/<name>/`
- Add them to `.claude-plugin/marketplace.json`
- Validate:
```bash
claude plugin validate .
```
