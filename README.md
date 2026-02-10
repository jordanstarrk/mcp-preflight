# mcp-preflight
[![Downloads](https://static.pepy.tech/badge/mcp-preflight)](https://pepy.tech/project/mcp-preflight)
[![PyPI version](https://img.shields.io/pypi/v/mcp-preflight.svg)](https://pypi.org/project/mcp-preflight/)

`ls -la` for MCP servers. See what an MCP server exposes before you connect it.

## Install

```bash
pipx install mcp-preflight
```

## Quick start

```bash
mcp-preflight "npx @modelcontextprotocol/server-filesystem /tmp"
```

## Example output

```text
my-server (MCP 2025-03-26)

  Caution: the server process runs locally without sandboxing.
  Use --isolate-home to prevent access to your real HOME directory.

  Tools:
    🟢 list_items     "List all items in the database"
    🟢 get_item       "Get a single item by ID"
    🟡 create_item    "Create a new item"
    🟡 update_item    "Update an existing item"
    🔴 delete_item    "Permanently delete an item"

  Resources:
    📄 my-server://items
    📄 my-server://items/{id}

  Prompts:
    💬 analyze_items (project_name)

  Notes:
    ℹ️  timeout: mcp list_resources

  Risk: 2 write, 1 destructive, 2 read-only
```

## Common workflows

```bash
# Run against your own server
mcp-preflight "uv run server.py"
mcp-preflight "npx my-mcp-server"
mcp-preflight "python3 /path/to/server.py"

# Save a report (JSON)
mcp-preflight --save report.json "uv run server.py"

# Diff two saved reports
mcp-preflight diff before.json after.json

# JSON output
mcp-preflight --json "uv run server.py"
```

## Notes

- Runs the server locally.
- Enumerates exposed MCP capabilities.

<details>
<summary>Auth-gated servers / custom env</summary>

Some MCP servers only reveal tools/resources after authentication. `mcp-preflight` does not run login flows, so it may report capabilities as not enumerable until credentials are provided.

```bash
# Pass a token via env
mcp-preflight --env GITSCRUM_TOKEN=... "npx -y @gitscrum-studio/mcp-server"

# Point HOME (and XDG_* dirs) somewhere else (useful for servers that read ~/.config, ~/.local, etc.)
mcp-preflight --home /tmp/mcp-preflight-home "npx -y @gitscrum-studio/mcp-server"

# Isolate HOME entirely to reduce side effects/pollution
mcp-preflight --isolate-home "npx -y @gitscrum-studio/mcp-server"
```

</details>

<details>
<summary>Risk classification heuristic</summary>

Based on tool names and descriptions (conservative by default):

- 🟢 **read-only**: `get`, `list`, `search`, `read`, `fetch`, `find`, `show`, `view`
- 🟡 **write**: `create`, `add`, `update`, `set`, `send`, `write`, `upload`
- 🔴 **destructive**: `delete`, `remove`, `destroy`, `drop`, `purge`, `clear`, `reset`
- Unknown → 🟡 (assume write until proven otherwise)

</details>

<details>
<summary>Signals (heuristic)</summary>

`mcp-preflight` can emit “signals” based on text matching (best-effort). These are hints, not guarantees, and may have false positives/negatives.

Disable with:

```bash
mcp-preflight --no-signals "uv run server.py"
```

</details>

## Non-goals

- No sandboxing
- No policy enforcement
- No runtime analysis

This tool inspects exposed MCP capabilities. It does not call tools (`call_tool`).

## Support

- Bugs / feature requests: `https://github.com/jordanstarrk/mcp-preflight/issues`
