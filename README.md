# mcp-preflight

See what an MCP server exposes before you trust or connect it.

## TLDR

Run one command.  
Get a list of tools, resources, and prompts.  
See read / write / destructive capabilities up front.

## Usage

```bash
mcp-preflight "uv run server.py"
```

### Other examples
```bash
mcp-preflight "npx my-mcp-server"
mcp-preflight "python /path/to/server.py"
```

### Diff two saved reports
```bash
mcp-preflight diff before.json after.json
```

## Example output
 my-server (MCP 2025-03-26)

  Tools:
- 🟢 list_items        "List all items in the database"
- 🟢 get_item          "Get a single item by ID"
- 🟡 create_item       "Create a new item"
- 🟡 update_item       "Update an existing item"
- 🔴 delete_item       "Permanently delete an item"

Risk: 2 write, 1 destructive, 2 read-only

## Risk classification
- 🟢 read-only
- 🟡 write
- 🔴 destructive

Based on tool names and descriptions. Conservative by default.

## Non-goals

- No sandboxing
- No policy enforcement
- No runtime analysis

This tool inspects. It does not execute.