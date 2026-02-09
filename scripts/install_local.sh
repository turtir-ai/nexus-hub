#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[nexus-hub] marketplace root: $ROOT"

echo "[nexus-hub] validating marketplace + plugin..."
claude plugin validate "$ROOT"

echo "[nexus-hub] adding local marketplace (ok if already added)..."
claude plugin marketplace add "$ROOT" >/dev/null 2>&1 || true

echo "[nexus-hub] installing nexus-core@turtir-ai (ok if already installed)..."
claude plugin install nexus-core@turtir-ai >/dev/null 2>&1 || true

echo "[nexus-hub] installed plugins:"
claude plugin list

cat <<'TXT'

Next:
1) Restart Claude Code so updated hooks/commands/skills load.
2) If you have legacy hooks in ~/.claude/settings.json, keep one source of truth:
   - plugin-only (recommended): jq '.hooks = {}' ~/.claude/settings.json > ~/.claude/settings.json.tmp && mv ~/.claude/settings.json.tmp ~/.claude/settings.json

TXT

