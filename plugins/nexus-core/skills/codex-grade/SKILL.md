---
name: codex-grade
description: Use when the user wants higher-quality / more deterministic coding output (\"Codex-grade\"), asks for evidence-first development, or complains about weak/unstable LLM results. Enforces a strict workflow: evidence -> minimal patch -> deterministic verification -> evidence-backed report.
tools: Read, Glob, Grep, Bash
---

# Codex-Grade Workflow (NEXUS)

This skill exists to make outputs **predictable and testable** even when the underlying LLM is weaker.

## Hard Rules

- **No claims without evidence.** If you say \"fixed\", you must show passing commands/output.
- **Small patches only.** Prefer the smallest diff that solves the issue.
- **Deterministic verification required** after meaningful edits.
- If the **quality gate rolls back**, stop and fix the failure before continuing.

## Default Workflow (Mandatory)

1. Restate the request in one sentence.
2. Collect evidence:
   - Read the relevant files
   - Run the smallest diagnostic command(s)
3. Implement minimal, targeted patch.
4. Verify deterministically (tests/lint/compile).
5. Report in this order:
   1) What I changed
   2) Evidence (exact commands + key output)
   3) File list
   4) Next command

## Minimum Verification Set

If the project is Python:
```bash
python3 -m compileall -q .
python3 -m pytest -q || true
ruff check . || true
```

If the project is Node:
```bash
npm test --silent || true
```

## NEXUS Evidence Sources

When available, use NEXUS state files as evidence:
- `~/.claude/state/performance_metrics.json`
- `~/.claude/state/learning_patterns.json`
- `~/.claude/state/incidents.jsonl`
- `~/.claude/state/fix_queue.jsonl`
- `~/.claude/state/quality_report.json`

