---
name: mcp-skillpacks
description: Use when the user asks to add MCP servers, configure .mcp.json, add external tools (browser, docs, github), or wants a plugin-based skill pack system (frontend/cyber/etc). Provides safe, portable MCP setup patterns for Claude Code.
tools: Read, Glob, Grep, Bash
---

# MCP + Skill Packs (NEXUS Hub)

Goal: Make Claude Code outputs more reliable by giving it **real tools** (MCP servers) and a **repeatable skill pack structure**.

## MCP Basics

Claude Code loads MCP servers from:

1. Project `.mcp.json` (recommended for portability; check into git)
2. Global config (`~/.claude.json` project section)
3. Plugin-provided `.mcp.json` (for bundling tools with plugins)

## `.mcp.json` Format (Canonical)

Top-level JSON object mapping `server-name -> config`:

```json
{
  "server-name": {
    "type": "http",
    "url": "https://mcp.example.com/api"
  }
}
```

## Safe Default Recommendations

If you want \"Codex-grade\" correctness, the highest ROI MCP categories are:

- **Docs** (reduces hallucinated APIs)
- **Browser automation** (verifies UI claims with screenshots)
- **GitHub/Issue trackers** (keeps work aligned with tickets/PRs)

Exact server configs depend on the provider. Use this pattern and swap the server details:

```json
{
  "docs": {
    "type": "http",
    "url": "https://<your-docs-mcp>/mcp",
    "headers": {
      "Authorization": "Bearer ${DOCS_MCP_TOKEN}"
    }
  }
}
```

## Skill Pack Structure (In This Marketplace)

For extensibility, keep skill packs as either:

- a **plugin** (best when it bundles hooks/commands/MCP servers), or
- a **skills/** folder inside an existing plugin (best for lightweight guidance/workflows)

Recommended packs to create next:

- `frontend-pack`: UI testing + component conventions + Playwright MCP instructions
- `cybersecurity-defensive-pack`: secure code review checklists, SAST, dependency audit workflows (no exploit/weaponization)
- `data-extraction-pack`: parsing/normalization + evidence logging patterns

## Debugging MCP

Use:
```bash
claude --mcp-debug
```

If an MCP server fails to start:
- confirm the `command`/`url` exists
- confirm required env vars exist
- keep configs portable (prefer `${VAR}` placeholders)

