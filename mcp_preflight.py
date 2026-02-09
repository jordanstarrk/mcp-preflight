"""
mcp-preflight — See what an MCP server does before you trust it.

Usage:
  mcp-preflight "uv run server.py"
  mcp-preflight "npx my-mcp-server"
  mcp-preflight "python /path/to/server.py"
  mcp-preflight --save report.json "uv run server.py"
  mcp-preflight diff before.json after.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Exception groups are built-in in Python 3.11+, but on 3.10 they're provided by the
# `exceptiongroup` backport (often installed as a transitive dependency).
try:  # Python 3.11+
    _BaseExceptionGroup = BaseExceptionGroup  # type: ignore[name-defined]
except NameError:  # Python <= 3.10
    try:
        from exceptiongroup import BaseExceptionGroup as _BaseExceptionGroup  # type: ignore
    except Exception:  # pragma: no cover
        _BaseExceptionGroup = None


# ── Risk classification ──────────────────────────────────────

READ_PATTERNS = re.compile(
    r"\b(get|list|search|read|fetch|find|show|view)\b",
    re.IGNORECASE,
)
WRITE_PATTERNS = re.compile(
    r"\b(create|add|update|set|send|write|upload)\b",
    re.IGNORECASE,
)
DESTRUCTIVE_PATTERNS = re.compile(
    r"\b(delete|remove|destroy|drop|purge|clear|reset)\b",
    re.IGNORECASE,
)


def classify_tool(name: str, description: str) -> tuple[str, str]:
    """Classify a tool's risk level from its name and description."""
    # Normalize tool names like `get_file_info` so \bget\b matches:
    # underscores/dashes are "word chars" in regex, so treat them as separators.
    text = f"{name} {description}"
    text = re.sub(r"[_-]+", " ", text)

    if DESTRUCTIVE_PATTERNS.search(text):
        return "🔴", "destructive"
    if WRITE_PATTERNS.search(text):
        return "🟡", "write"
    if READ_PATTERNS.search(text):
        return "🟢", "read"
    # Unknown → 🟡 (assume write until proven otherwise).
    return "🟡", "write"

def _normalize_text(s: object) -> str:
    return " ".join(str(s).split())


def _tool_dict(tool) -> dict:
    desc = tool.description or "(no description)"
    icon, risk = classify_tool(tool.name, desc)
    return {"name": tool.name, "description": _normalize_text(desc), "risk": risk, "icon": icon}


def _prompt_dict(prompt) -> dict:
    args = []
    if hasattr(prompt, "arguments") and prompt.arguments:
        args = [a.name for a in prompt.arguments]
    desc = getattr(prompt, "description", None)
    return {
        "name": prompt.name,
        "arguments": args,
        "description": _normalize_text(desc) if desc else None,
    }


SUSPICIOUS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("prompt injection phrase", re.compile(r"\b(ignore|disregard)\b.*\b(instructions|system|developer)\b", re.I)),
    ("secret exfiltration", re.compile(r"\b(exfiltrat|steal|leak)\w*\b", re.I)),
    ("do not tell user", re.compile(r"\b(don't|do not)\b.*\b(tell|mention|reveal)\b.*\b(user)\b", re.I)),
    ("system prompt mention", re.compile(r"\b(system prompt|developer message)\b", re.I)),
    # base64 shows up in benign contexts (e.g. image tools), so keep this focused on actual key material.
    ("encoded secret material", re.compile(r"\bBEGIN [A-Z ]+ KEY\b", re.I)),
    ("shell download hint", re.compile(r"\b(curl|wget)\b\s+https?://", re.I)),
]


def collect_signals(
    tools: list[dict], resource_uris: list[str], template_uris: list[str], prompts: list[dict]
) -> list[dict]:
    signals: list[dict] = []

    def scan(kind: str, name: str, text: str):
        for label, pat in SUSPICIOUS_PATTERNS:
            if pat.search(text):
                signals.append(
                    {
                        "kind": kind,
                        "name": name,
                        "rule": label,
                        "snippet": text[:200] + ("..." if len(text) > 200 else ""),
                    }
                )

    for t in tools:
        scan("tool", t["name"], f'{t["name"]} {t["description"]}')
    for uri in resource_uris:
        scan("resource", uri, uri)
    for uri in template_uris:
        scan("resource_template", uri, uri)
    for p in prompts:
        text = f'{p["name"]} {" ".join(p.get("arguments") or [])} {p.get("description") or ""}'.strip()
        scan("prompt", p["name"], text)

    # Stable ordering for screenshots/diffs
    signals.sort(key=lambda s: (s.get("kind", ""), s.get("name", ""), s.get("rule", "")))
    return signals


# ── Output formatting ────────────────────────────────────────

def print_header(server_name: str, protocol_version: str):
    print(f"{server_name} (MCP {protocol_version})\n")


def print_tools(tools: list[dict]):
    if not tools:
        print("  Tools: none\n")
        return

    name_width = min(max(len(t["name"]) for t in tools), 28)
    term_width = shutil.get_terminal_size(fallback=(100, 20)).columns

    print("  Tools:")
    for tool in tools:
        icon = tool["icon"]
        desc = tool["description"].replace('"', '\\"')

        prefix = f'    {icon} {tool["name"]:<{name_width}} '
        quote_prefix = prefix + '"'
        cont_prefix = " " * len(quote_prefix)
        available = max(20, term_width - len(quote_prefix) - 1)  # -1 for closing quote

        wrapped = textwrap.wrap(desc, width=available) or [""]
        if len(wrapped) == 1:
            print(f'{quote_prefix}{wrapped[0]}"')
        else:
            print(f"{quote_prefix}{wrapped[0]}")
            for line in wrapped[1:-1]:
                print(f"{cont_prefix}{line}")
            print(f'{cont_prefix}{wrapped[-1]}"')
            print()

    print()


def print_resources(resources, templates):
    has_any = resources or templates
    if not has_any:
        print("  Resources: none\n")
        return

    print("  Resources:")
    for uri in sorted([r.uri for r in resources]):
        print(f"    📄 {uri}")
    for uri in sorted([t.uriTemplate for t in templates]):
        print(f"    📄 {uri}")
    print()


def print_prompts(prompts):
    if not prompts:
        print("  Prompts: none\n")
        return

    print("  Prompts:")
    for p in sorted(prompts, key=lambda x: x.get("name", "")):
        args = ""
        if p.get("arguments"):
            arg_names = p["arguments"]
            args = f" ({', '.join(arg_names)})"
        print(f"    💬 {p['name']}{args}")
    print()


def print_signals(signals: list[dict]):
    if not signals:
        return
    print("  Signals (heuristic):")
    for s in signals:
        name = s.get("name") or ""
        rule = s.get("rule") or "signal"
        print(f"    ⚠️  {rule}: {s['kind']} {name}")
    print("    (may be false positives/negatives)")
    print()

def print_notes(notes: list[dict]):
    if not notes:
        return
    print("  Notes:")
    for n in notes:
        rule = n.get("rule") or "note"
        name = n.get("name") or ""
        print(f"    ℹ️  {rule}: {n.get('kind')} {name}")
    print()


def print_risk_summary(counts: dict):
    parts = []
    if counts.get("write"):
        parts.append(f"{counts['write']} write")
    if counts.get("destructive"):
        parts.append(f"{counts['destructive']} destructive")
    if counts.get("read"):
        parts.append(f"{counts['read']} read-only")

    print(f"  Risk: {', '.join(parts)}")
    print()


# ── Main ─────────────────────────────────────────────────────

RISK_PRIORITY = {"destructive": 0, "write": 1, "read": 2}


def count_risks(tools: list[dict]) -> dict:
    counts = {"read": 0, "write": 0, "destructive": 0}
    for t in tools:
        counts[t["risk"]] = counts.get(t["risk"], 0) + 1
    return counts


def _contains_timeout(exc: BaseException) -> bool:
    """Return True if exc (possibly an ExceptionGroup) contains a timeout."""
    # In practice, timeouts often surface as cancellation inside anyio TaskGroups.
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, asyncio.CancelledError)):
        return True
    # anyio cancellation/stream teardown frequently shows up as BrokenResourceError/ClosedResourceError.
    if type(exc).__name__ in {"BrokenResourceError", "ClosedResourceError"}:
        return True
    # TimeoutError may be wrapped in an ExceptionGroup/BaseExceptionGroup.
    if _BaseExceptionGroup is not None and isinstance(exc, _BaseExceptionGroup):  # type: ignore[arg-type]
        for sub in getattr(exc, "exceptions", ()):
            if _contains_timeout(sub):
                return True
    return False


def _build_report(
    *,
    scanned_command: list[str],
    server_name: str,
    protocol_version: str,
    tools: list[dict],
    resource_uris: list[str],
    template_uris: list[str],
    prompts: list[dict],
    signals: list[dict],
    notes: list[dict],
    risk: dict,
) -> dict:
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "scannedCommand": scanned_command,
        "server": {"name": server_name, "protocolVersion": protocol_version},
        "tools": tools,
        "resources": resource_uris,
        "resourceTemplates": template_uris,
        "prompts": prompts,
        "risk": risk,
        "signals": signals,
        "notes": notes,
    }


async def inspect(
    command: str,
    args: list[str],
    *,
    emit_text: bool = True,
    timeout_s: float = 10.0,
    errlog: TextIO | None = None,
    include_signals: bool = True,
) -> dict:
    server_params = StdioServerParameters(command=command, args=args)

    async with stdio_client(server_params, errlog=errlog or sys.stderr) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            result = await asyncio.wait_for(session.initialize(), timeout=timeout_s)

            server_name = "unknown"
            if hasattr(result, "serverInfo") and result.serverInfo:
                server_name = result.serverInfo.name
            protocol_version = getattr(result, "protocolVersion", "unknown")

            # Tools (required)
            tools_raw = (await asyncio.wait_for(session.list_tools(), timeout=timeout_s)).tools
            tools = [_tool_dict(t) for t in tools_raw]
            tools.sort(key=lambda t: (RISK_PRIORITY.get(t["risk"], 9), t["name"]))
            risk = count_risks(tools)

            # Resources (optional)
            resources = []
            templates = []
            notes: list[dict] = []
            try:
                resources = (await asyncio.wait_for(session.list_resources(), timeout=timeout_s)).resources
            except asyncio.TimeoutError:
                notes.append(
                    {"kind": "mcp", "name": "list_resources", "rule": "timeout", "snippet": f"Timed out after {timeout_s}s"}
                )
            except Exception:
                pass
            try:
                templates = (
                    await asyncio.wait_for(session.list_resource_templates(), timeout=timeout_s)
                ).resourceTemplates
            except asyncio.TimeoutError:
                notes.append(
                    {
                        "kind": "mcp",
                        "name": "list_resource_templates",
                        "rule": "timeout",
                        "snippet": f"Timed out after {timeout_s}s",
                    }
                )
            except Exception:
                pass
            resource_uris = sorted([r.uri for r in resources])
            template_uris = sorted([t.uriTemplate for t in templates])

            # Prompts (optional)
            prompts = []
            try:
                prompts = (await asyncio.wait_for(session.list_prompts(), timeout=timeout_s)).prompts
            except asyncio.TimeoutError:
                notes.append(
                    {"kind": "mcp", "name": "list_prompts", "rule": "timeout", "snippet": f"Timed out after {timeout_s}s"}
                )
            except Exception:
                pass
            prompts_info = [_prompt_dict(p) for p in prompts]
            prompts_info.sort(key=lambda p: p.get("name", ""))

            signals: list[dict] = []
            if include_signals:
                signals = collect_signals(tools, resource_uris, template_uris, prompts_info)

            notes.sort(key=lambda n: (n.get("kind", ""), n.get("name", ""), n.get("rule", "")))

            if emit_text:
                print_header(server_name, protocol_version)
                print("  Note: this runs the server locally; it does not sandbox the process.\n")
                print_tools(tools)
                print_resources(resources, templates)
                print_prompts(prompts_info)
                print_signals(signals)
                print_notes(notes)
                print_risk_summary(risk)

            return _build_report(
                scanned_command=[command, *args],
                server_name=server_name,
                protocol_version=protocol_version,
                tools=tools,
                resource_uris=resource_uris,
                template_uris=template_uris,
                prompts=prompts_info,
                signals=signals,
                notes=notes,
                risk=risk,
            )


def _diff_reports(before: dict, after: dict) -> str:
    def tool_map(r: dict) -> dict[str, dict]:
        return {t["name"]: t for t in r.get("tools", [])}

    before_tools = tool_map(before)
    after_tools = tool_map(after)
    added = sorted(set(after_tools) - set(before_tools))
    removed = sorted(set(before_tools) - set(after_tools))
    changed_risk = sorted(
        name
        for name in (set(before_tools) & set(after_tools))
        if before_tools[name].get("risk") != after_tools[name].get("risk")
    )

    def list_diff(before_list: list[str], after_list: list[str]) -> tuple[list[str], list[str]]:
        return sorted(set(after_list) - set(before_list)), sorted(set(before_list) - set(after_list))

    res_added, res_removed = list_diff(before.get("resources", []), after.get("resources", []))
    tmpl_added, tmpl_removed = list_diff(before.get("resourceTemplates", []), after.get("resourceTemplates", []))

    before_prompts = sorted(p.get("name") for p in before.get("prompts", []) if p.get("name"))
    after_prompts = sorted(p.get("name") for p in after.get("prompts", []) if p.get("name"))
    pr_added, pr_removed = list_diff(before_prompts, after_prompts)

    def fmt_risk(r: dict) -> str:
        rr = r.get("risk", {}) if isinstance(r, dict) else {}
        return f'{rr.get("write", 0)} write, {rr.get("destructive", 0)} destructive, {rr.get("read", 0)} read-only'

    lines: list[str] = []
    lines.append("Diff\n")
    lines.append(f'  Before: {before.get("server", {}).get("name", "unknown")} ({fmt_risk(before)})')
    lines.append(f'  After:  {after.get("server", {}).get("name", "unknown")} ({fmt_risk(after)})\n')

    if added or removed or changed_risk:
        lines.append("  Tools:")
        for name in added:
            lines.append(f'    + {name} ({after_tools[name].get("risk")})')
        for name in removed:
            lines.append(f'    - {name} ({before_tools[name].get("risk")})')
        for name in changed_risk:
            lines.append(f'    ~ {name}: {before_tools[name].get("risk")} -> {after_tools[name].get("risk")}')
        lines.append("")

    if res_added or res_removed or tmpl_added or tmpl_removed:
        lines.append("  Resources:")
        for uri in res_added:
            lines.append(f"    + {uri}")
        for uri in res_removed:
            lines.append(f"    - {uri}")
        for uri in tmpl_added:
            lines.append(f"    + {uri}")
        for uri in tmpl_removed:
            lines.append(f"    - {uri}")
        lines.append("")

    if pr_added or pr_removed:
        lines.append("  Prompts:")
        for name in pr_added:
            lines.append(f"    + {name}")
        for name in pr_removed:
            lines.append(f"    - {name}")
        lines.append("")

    if not (added or removed or changed_risk or res_added or res_removed or tmpl_added or tmpl_removed or pr_added or pr_removed):
        lines.append("  No changes detected.\n")

    return "\n".join(lines).rstrip() + "\n"


def main():
    if len(sys.argv) < 2:
        print('Usage: mcp-preflight "uv run server.py"')
        print('  mcp-preflight "npx my-mcp-server"')
        print('  mcp-preflight "python /path/to/server.py"')
        print("  mcp-preflight diff before.json after.json")
        sys.exit(1)

    if sys.argv[1] == "diff":
        parser = argparse.ArgumentParser(prog="mcp-preflight diff", add_help=True)
        parser.add_argument("before", type=Path)
        parser.add_argument("after", type=Path)
        ns = parser.parse_args(sys.argv[2:])

        before = json.loads(ns.before.read_text(encoding="utf-8"))
        after = json.loads(ns.after.read_text(encoding="utf-8"))
        sys.stdout.write(_diff_reports(before, after))
        return

    parser = argparse.ArgumentParser(
        prog="mcp-preflight",
        add_help=True,
        description="Inspect an MCP server's exposed capabilities (tools/resources/prompts).",
        epilog="Note: this runs the server process locally; it does not sandbox the server.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="Print machine-readable JSON")
    parser.add_argument("--save", type=Path, help="Save JSON report to a file")
    parser.add_argument("--timeout", type=float, default=10.0, help="Timeout (seconds) for MCP calls (default: 10)")
    parser.add_argument("--no-signals", action="store_true", help="Disable heuristic signal scanning/output")
    vgroup = parser.add_mutually_exclusive_group()
    vgroup.add_argument("--quiet", action="store_true", help="Suppress server stderr (even on failure)")
    vgroup.add_argument("--verbose", action="store_true", help="Print server stderr (even on success)")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Server command (quoted or split)")
    ns = parser.parse_args(sys.argv[1:])

    if not ns.command:
        print('Usage: mcp-preflight "uv run server.py"')
        sys.exit(1)

    # Accept a single quoted command string (e.g. "uv run server.py") or split args (e.g. uv run server.py).
    if len(ns.command) == 1:
        parts = shlex.split(ns.command[0])
    else:
        parts = ns.command

    if not parts:
        print('Usage: mcp-preflight "uv run server.py"')
        sys.exit(1)

    command = parts[0]
    args = parts[1:]

    emit_text = not ns.as_json

    errlog: TextIO
    errbuf: TextIO | None = None
    if ns.quiet:
        errlog = open(os.devnull, "w")
    else:
        errbuf = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        errlog = errbuf

    try:
        report = asyncio.run(
            inspect(
                command,
                args,
                emit_text=emit_text,
                timeout_s=ns.timeout,
                errlog=errlog,
                include_signals=not ns.no_signals,
            )
        )
        if ns.verbose and errbuf is not None and not ns.quiet:
            errbuf.seek(0)
            server_err = errbuf.read().strip()
            if server_err:
                sys.stderr.write("\n[server stderr]\n" + server_err + "\n")
    except BaseException as e:
        is_timeout = _contains_timeout(e)
        server_err = ""
        if errbuf is not None and not ns.quiet:
            errbuf.seek(0)
            server_err = errbuf.read().strip()
            if server_err:
                sys.stderr.write("\n[server stderr]\n" + server_err + "\n")
        if not server_err:
            sys.stderr.write(
                "Hint: if the server writes logs to stdout, it can break MCP stdio. Ensure server logs go to stderr.\n"
            )
        if is_timeout:
            sys.stderr.write(f"mcp-preflight: timed out after {ns.timeout}s\n")
        else:
            sys.stderr.write(f"mcp-preflight: error: {e}\n")
        raise SystemExit(1)
    finally:
        try:
            errlog.close()
        except Exception:
            pass

    if ns.save:
        ns.save.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if ns.as_json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()