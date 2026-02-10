# mcp-preflight
[![Downloads](https://static.pepy.tech/badge/mcp-preflight)](https://pepy.tech/project/mcp-preflight)
[![PyPI version](https://img.shields.io/pypi/v/mcp-preflight.svg)](https://pypi.org/project/mcp-preflight/)

`ls -la` for MCP servers. See what an MCP server exposes before you connect it.

## Install

Recommended (CLI):

```bash
pipx install mcp-preflight
```

## Usage

```bash
mcp-preflight "npx @modelcontextprotocol/server-filesystem /tmp"
```

### Example output

```text
my-server (MCP 2025-03-26)

  Note: this runs the server locally; it does not sandbox the process.

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

  Signals (heuristic):
    ⚠️  system prompt mention: prompt analyze_items
    (may be false positives/negatives)

  Notes:
    ℹ️  timeout: mcp list_resources

  Risk: 2 write, 1 destructive, 2 read-only
```

### Run against your own server

```bash
mcp-preflight "uv run server.py"
mcp-preflight "npx my-mcp-server"
mcp-preflight "python3 /path/to/server.py"
```

### Save a report (JSON)

```bash
mcp-preflight --save report.json "uv run server.py"
```

### Diff two saved reports

```bash
mcp-preflight diff before.json after.json
```

### JSON output

```bash
mcp-preflight --json "uv run server.py"
```

### Alternative install (not recommended for global installs)

```bash
pip install mcp-preflight
```

## Risk classification

Based on tool names and descriptions (conservative by default):

- 🟢 **read-only**: `get`, `list`, `search`, `read`, `fetch`, `find`, `show`, `view`
- 🟡 **write**: `create`, `add`, `update`, `set`, `send`, `write`, `upload`
- 🔴 **destructive**: `delete`, `remove`, `destroy`, `drop`, `purge`, `clear`, `reset`
- Unknown → 🟡 (assume write until proven otherwise)

## Non-goals

- No sandboxing
- No policy enforcement
- No runtime analysis

This tool inspects exposed MCP capabilities. It does not call tools (`call_tool`).

## Support

- Bugs / feature requests: `https://github.com/jordanstarrk/mcp-preflight/issues`
