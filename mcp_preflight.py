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
from typing import Any, TextIO
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


def _tool_dict(tool: Any) -> dict:
    desc = tool.description or "(no description)"
    icon, risk = classify_tool(tool.name, desc)
    return {"name": tool.name, "description": _normalize_text(desc), "risk": risk, "icon": icon}


def _prompt_dict(prompt: Any) -> dict:
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
        u = str(uri)
        scan("resource", u, u)
    for uri in template_uris:
        u = str(uri)
        scan("resource_template", u, u)
    for p in prompts:
        text = f'{p["name"]} {" ".join(p.get("arguments") or [])} {p.get("description") or ""}'.strip()
        scan("prompt", p["name"], text)

    # Stable ordering for screenshots/diffs
    signals.sort(key=lambda s: (s.get("kind", ""), s.get("name", ""), s.get("rule", "")))
    return signals


# ── Output formatting ────────────────────────────────────────

def print_header(server_name: str, protocol_version: str) -> None:
    print(f"{server_name} (MCP {protocol_version})\n")


def print_tools(tools: list[dict]) -> None:
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


def print_resources(
    resource_uris: list[str], template_uris: list[str], *, supported: bool = True, had_error: bool = False
) -> None:
    has_any = resource_uris or template_uris
    if not has_any:
        if not supported:
            print("  Resources: not supported by server\n")
        elif had_error:
            print("  Resources: unknown (introspection failed)\n")
        else:
            print("  Resources: none\n")
        return

    print("  Resources:")
    for uri in sorted(resource_uris):
        print(f"    📄 {uri}")
    for uri in sorted(template_uris):
        print(f"    📄 {uri}")
    print()


def print_prompts(prompts: list[dict], *, supported: bool = True, had_error: bool = False) -> None:
    if not prompts:
        if not supported:
            print("  Prompts: not supported by server\n")
        elif had_error:
            print("  Prompts: unknown (introspection failed)\n")
        else:
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

def print_notes(notes: list[dict]) -> None:
    if not notes:
        return
    print("  Notes:")
    for n in notes:
        rule = n.get("rule") or "note"
        name = n.get("name") or ""
        snippet = n.get("snippet") or ""

        label = f"{name} ({rule})" if name else rule

        if snippet:
            # Show the first line, truncated for terminal readability.
            short = snippet.split("\n")[0][:120]
            if len(short) < len(snippet):
                short += "…"
            print(f"    ℹ️  {label}: {short}")
        else:
            print(f"    ℹ️  {label}")
    print()


def print_risk_summary(counts: dict) -> None:
    parts = []
    if counts.get("write"):
        parts.append(f"{counts['write']} write")
    if counts.get("destructive"):
        parts.append(f"{counts['destructive']} destructive")
    if counts.get("read"):
        parts.append(f"{counts['read']} read-only")

    print(f"  Risk: {', '.join(parts) if parts else 'none'}")
    print()


def print_text_report(report: dict) -> None:
    """Render a finalized report dict as human-readable text to stdout."""
    server = report.get("server", {})
    status = report.get("status", "ok")

    print_header(server.get("name", "unknown"), server.get("protocolVersion", "unknown"))
    print("  Caution: the server process runs locally without sandboxing.")
    print("  Use --isolate-home to prevent access to your real HOME directory.\n")

    if status == "auth_gated":
        print("  Status: 🔒 auth-gated (server did not enumerate capabilities without credentials)\n")
        return

    if status == "partial":
        print("  Status: ⚠️  partial (some MCP introspection calls failed)\n")

    print_tools(report.get("tools", []))

    capabilities = report.get("capabilities", {})
    notes = report.get("notes", [])
    resources_had_error = any(
        n.get("name") in ("list_resources", "list_resource_templates") for n in notes
    )
    prompts_had_error = any(n.get("name") == "list_prompts" for n in notes)

    print_resources(
        report.get("resources", []),
        report.get("resourceTemplates", []),
        supported=capabilities.get("resources", True),
        had_error=resources_had_error,
    )
    print_prompts(
        report.get("prompts", []),
        supported=capabilities.get("prompts", True),
        had_error=prompts_had_error,
    )
    print_signals(report.get("signals", []))
    print_notes(notes)
    print_risk_summary(report.get("risk", {}))


# ── Main ─────────────────────────────────────────────────────

RISK_PRIORITY = {"destructive": 0, "write": 1, "read": 2}

AUTH_HINT_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bno (authentication|auth) (token|credentials?)\b", re.I),
    re.compile(r"\b(authenticate|authentication) (required|needed)\b", re.I),
    re.compile(r"\bplease authenticate\b", re.I),
    re.compile(r"\bauth_login\b", re.I),
    re.compile(r"\blogin required\b", re.I),
    re.compile(r"\bunauthorized\b", re.I),
]

STACKTRACE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bReferenceError:\b"),
    re.compile(r"\bTypeError:"),
    re.compile(r"\bUnhandledPromiseRejection\b"),
    re.compile(r"\bunhandled errors? in a TaskGroup\b", re.I),
    re.compile(r"\bFatal error\b", re.I),
]


def _mark_partial(current: str) -> str:
    """Escalate status to 'partial' without downgrading from a worse status."""
    return current if current != "ok" else "partial"


def count_risks(tools: list[dict]) -> dict:
    counts = {"read": 0, "write": 0, "destructive": 0}
    for t in tools:
        counts[t["risk"]] = counts.get(t["risk"], 0) + 1
    return counts


def contains_timeout(exc: BaseException) -> bool:
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
            if contains_timeout(sub):
                return True
    return False


def _stderr_excerpt(server_err: str, *, max_chars: int = 1500) -> str:
    s = server_err.strip()
    if len(s) <= max_chars:
        return s
    # Prefer the end of stderr (often has the final error/stacktrace).
    tail = s[-max_chars:]
    # Avoid cutting in the middle of a line when possible.
    nl = tail.find("\n")
    if 0 <= nl <= 200:
        tail = tail[nl + 1 :]
    return "…\n" + tail


def stderr_notes(server_err: str) -> tuple[list[dict], dict]:
    """
    Return (notes, stderr_signals) derived from raw server stderr.
    stderr_signals is a small dict used for status classification.
    """
    notes: list[dict] = []
    text = _normalize_text(server_err)
    has_auth_hint = any(p.search(text) for p in AUTH_HINT_PATTERNS)
    has_stacktrace = any(p.search(server_err) for p in STACKTRACE_PATTERNS)
    if has_auth_hint:
        notes.append(
            {
                "kind": "server",
                "name": "stderr",
                "rule": "auth_hint",
                "snippet": _stderr_excerpt(server_err, max_chars=600)[:600],
            }
        )
    if has_stacktrace:
        notes.append(
            {
                "kind": "server",
                "name": "stderr",
                "rule": "startup_stacktrace",
                "snippet": _stderr_excerpt(server_err, max_chars=900)[:900],
            }
        )
    notes.sort(key=lambda n: (n.get("kind", ""), n.get("name", ""), n.get("rule", "")))
    return notes, {"has_auth_hint": has_auth_hint, "has_stacktrace": has_stacktrace}


def _relevant_stderr_lines(server_err: str, *, max_lines: int = 3) -> str:
    """
    Extract a small, high-signal subset of stderr for cleaner default output.

    Intended for auth-gated / startup error cases where full stack traces are noisy.
    """
    lines = [ln.rstrip() for ln in (server_err or "").splitlines() if ln.strip()]
    if not lines:
        return ""

    picked: list[str] = []
    for ln in lines:
        # Prefer auth hints and the first "fatal error" / exception line.
        if any(p.search(ln) for p in AUTH_HINT_PATTERNS) or re.search(r"\b(Fatal error|ReferenceError:|TypeError:|Error:)\b", ln):
            if ln not in picked:
                picked.append(ln)
        if len(picked) >= max_lines:
            break

    # Fallback: just show the first line or two.
    if not picked:
        picked = lines[: min(max_lines, 2)]

    return "\n".join(picked).strip()


def _build_report(
    *,
    scanned_command: list[str],
    server_name: str,
    protocol_version: str,
    capabilities: dict[str, bool],
    status: str,
    tools: list[dict],
    resource_uris: list[str],
    template_uris: list[str],
    prompts: list[dict],
    signals: list[dict],
    notes: list[dict],
    risk: dict,
    errors: list[dict] | None = None,
) -> dict:
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "scannedCommand": scanned_command,
        "server": {"name": server_name, "protocolVersion": protocol_version},
        "capabilities": capabilities,
        "status": status,
        "tools": tools,
        "resources": resource_uris,
        "resourceTemplates": template_uris,
        "prompts": prompts,
        "risk": risk,
        "signals": signals,
        "notes": notes,
        "errors": errors or [],
    }


async def inspect(
    command: str,
    args: list[str],
    *,
    timeout_s: float = 10.0,
    errlog: TextIO | None = None,
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
    include_signals: bool = True,
) -> dict:
    server_params = StdioServerParameters(command=command, args=args, env=env, cwd=cwd)

    async with stdio_client(server_params, errlog=errlog or sys.stderr) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            result = await asyncio.wait_for(session.initialize(), timeout=timeout_s)

            server_name = "unknown"
            if hasattr(result, "serverInfo") and result.serverInfo:
                server_name = result.serverInfo.name
            protocol_version = getattr(result, "protocolVersion", "unknown")

            # Read server-declared capabilities.
            caps = getattr(result, "capabilities", None)
            has_tools = caps is not None and getattr(caps, "tools", None) is not None
            has_resources = caps is not None and getattr(caps, "resources", None) is not None
            has_prompts = caps is not None and getattr(caps, "prompts", None) is not None

            status = "ok"
            errors: list[dict] = []
            notes: list[dict] = []

            # Tools — always attempt even if not declared (many servers omit the capability).
            tools: list[dict] = []
            try:
                tools_raw = (await asyncio.wait_for(session.list_tools(), timeout=timeout_s)).tools
                tools = [_tool_dict(t) for t in tools_raw]
                tools.sort(key=lambda t: (RISK_PRIORITY.get(t["risk"], 9), t["name"]))
            except asyncio.TimeoutError:
                status = _mark_partial(status)
                errors.append(
                    {
                        "kind": "mcp",
                        "name": "list_tools",
                        "rule": "timeout",
                        "snippet": f"Timed out after {timeout_s}s",
                    }
                )
            except Exception as e:
                status = _mark_partial(status)
                errors.append(
                    {
                        "kind": "mcp",
                        "name": "list_tools",
                        "rule": "error",
                        "snippet": _normalize_text(str(e)),
                    }
                )
            risk = count_risks(tools)

            # Resources — skip if server didn't declare the capability.
            resources = []
            templates = []
            if has_resources:
                try:
                    resources = (await asyncio.wait_for(session.list_resources(), timeout=timeout_s)).resources
                except asyncio.TimeoutError:
                    status = _mark_partial(status)
                    notes.append(
                        {"kind": "mcp", "name": "list_resources", "rule": "timeout", "snippet": f"Timed out after {timeout_s}s"}
                    )
                except Exception as e:
                    status = _mark_partial(status)
                    notes.append(
                        {"kind": "mcp", "name": "list_resources", "rule": "error", "snippet": _normalize_text(str(e))}
                    )
                try:
                    templates = (
                        await asyncio.wait_for(session.list_resource_templates(), timeout=timeout_s)
                    ).resourceTemplates
                except asyncio.TimeoutError:
                    status = _mark_partial(status)
                    notes.append(
                        {
                            "kind": "mcp",
                            "name": "list_resource_templates",
                            "rule": "timeout",
                            "snippet": f"Timed out after {timeout_s}s",
                        }
                    )
                except Exception as e:
                    status = _mark_partial(status)
                    notes.append(
                        {"kind": "mcp", "name": "list_resource_templates", "rule": "error", "snippet": _normalize_text(str(e))}
                    )
            resource_uris = sorted([str(r.uri) for r in resources])
            template_uris = sorted([str(t.uriTemplate) for t in templates])

            # Prompts — skip if server didn't declare the capability.
            prompts = []
            if has_prompts:
                try:
                    prompts = (await asyncio.wait_for(session.list_prompts(), timeout=timeout_s)).prompts
                except asyncio.TimeoutError:
                    status = _mark_partial(status)
                    notes.append(
                        {"kind": "mcp", "name": "list_prompts", "rule": "timeout", "snippet": f"Timed out after {timeout_s}s"}
                    )
                except Exception as e:
                    status = _mark_partial(status)
                    notes.append(
                        {"kind": "mcp", "name": "list_prompts", "rule": "error", "snippet": _normalize_text(str(e))}
                    )
            prompts_info = [_prompt_dict(p) for p in prompts]
            prompts_info.sort(key=lambda p: p.get("name", ""))

            signals: list[dict] = []
            if include_signals:
                signals = collect_signals(tools, resource_uris, template_uris, prompts_info)

            notes.sort(key=lambda n: (n.get("kind", ""), n.get("name", ""), n.get("rule", "")))

            return _build_report(
                scanned_command=[command, *args],
                server_name=server_name,
                protocol_version=protocol_version,
                capabilities={"tools": has_tools, "resources": has_resources, "prompts": has_prompts},
                status=status,
                tools=tools,
                resource_uris=resource_uris,
                template_uris=template_uris,
                prompts=prompts_info,
                signals=signals,
                notes=notes,
                risk=risk,
                errors=errors,
            )


def diff_reports(before: dict, after: dict) -> str:
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


def _report_json(report: dict) -> str:
    """Serialize a report dict to a stable JSON string."""
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def _build_server_env(ns: argparse.Namespace) -> tuple[dict[str, str], tempfile.TemporaryDirectory[str] | None]:
    """
    Build the environment dict and optional temp-home for the server process.

    Handles --env, --home, and --isolate-home.
    Returns (server_env, temp_home_ctx).  Caller must clean up temp_home_ctx.
    """
    server_env = dict(os.environ)
    for item in ns.env or []:
        if "=" not in item:
            raise SystemExit(f"mcp-preflight: --env must be KEY=VALUE (got {item!r})")
        k, v = item.split("=", 1)
        server_env[k] = v

    temp_home_ctx: tempfile.TemporaryDirectory[str] | None = None
    if ns.isolate_home:
        temp_home_ctx = tempfile.TemporaryDirectory(prefix="mcp-preflight-home-")
        home_dir: Path | None = Path(temp_home_ctx.name)
    elif ns.home:
        home_dir = ns.home
    else:
        home_dir = None

    if home_dir is not None:
        server_env["HOME"] = str(home_dir)
        server_env["XDG_CONFIG_HOME"] = str(home_dir / ".config")
        server_env["XDG_DATA_HOME"] = str(home_dir / ".local" / "share")
        server_env["XDG_CACHE_HOME"] = str(home_dir / ".cache")

    return server_env, temp_home_ctx


def _read_captured_stderr(errbuf: TextIO | None) -> str:
    """Read and return captured stderr content, or empty string if nothing was captured."""
    if errbuf is None:
        return ""
    errbuf.seek(0)
    return errbuf.read().strip()


def _postprocess_success(report: dict, server_err: str, *, verbose: bool) -> None:
    """
    Post-process a successful inspect() report using captured stderr.

    Mutates ``report`` in place: merges stderr-derived notes, sets auth_gated status.
    """
    if server_err:
        notes, signals = stderr_notes(server_err)
        if notes:
            report["notes"] = sorted(
                (report.get("notes") or []) + notes,
                key=lambda n: (n.get("kind", ""), n.get("name", ""), n.get("rule", "")),
            )

        if signals.get("has_auth_hint") and (
            not report.get("tools")
            and not report.get("resources")
            and not report.get("resourceTemplates")
            and not report.get("prompts")
        ):
            report["status"] = "auth_gated"

    if verbose and server_err:
        sys.stderr.write("\n[server stderr]\n" + server_err + "\n")


def _handle_inspect_failure(
    exc: BaseException,
    *,
    server_err: str,
    command: str,
    args: list[str],
    timeout_s: float,
) -> tuple[dict, str]:
    """
    Build a failure report and user-facing error message from a failed inspect().

    Returns (report, error_message).
    """
    is_timeout = contains_timeout(exc)
    stderr_notes_list: list[dict] = []
    stderr_flags: dict = {}

    if server_err:
        stderr_notes_list, stderr_flags = stderr_notes(server_err)

        # If stderr contains a real stacktrace, it's not a timeout even if the
        # underlying I/O exception looks like cancellation/stream teardown.
        if stderr_flags.get("has_stacktrace"):
            is_timeout = False

    if stderr_flags.get("has_auth_hint"):
        status = "auth_required"
    else:
        status = "timeout" if is_timeout else "startup_error"

    stack_note = next((n for n in stderr_notes_list if n.get("rule") == "startup_stacktrace"), None)
    if is_timeout:
        err_snippet = f"Timed out after {timeout_s}s"
    elif stack_note and stack_note.get("snippet"):
        # Prefer the server's own stacktrace over anyio/TaskGroup wrapper errors.
        err_snippet = str(stack_note["snippet"])
    else:
        err_snippet = _normalize_text(str(exc))

    report = _build_report(
        scanned_command=[command, *args],
        server_name="unknown",
        protocol_version="unknown",
        capabilities={"tools": False, "resources": False, "prompts": False},
        status=status,
        tools=[],
        resource_uris=[],
        template_uris=[],
        prompts=[],
        signals=[],
        notes=stderr_notes_list,
        risk={"read": 0, "write": 0, "destructive": 0},
        errors=[
            {
                "kind": "mcp",
                "name": "initialize",
                "rule": "timeout" if is_timeout else "error",
                "snippet": err_snippet,
            }
        ],
    )

    # Build a concise user-facing error message.
    if is_timeout:
        error_message = f"mcp-preflight: timed out after {timeout_s}s"
    elif stderr_flags.get("has_auth_hint"):
        error_message = (
            "mcp-preflight: 🔒 authentication required (the MCP server did not start without credentials)\n"
            "Hint: re-run with --verbose to see server stderr, or pass credentials via --env/--home."
        )
    elif stack_note:
        error_message = "mcp-preflight: server crashed during startup (see stderr above)"
    else:
        error_message = f"mcp-preflight: error: {_normalize_text(str(exc))}"

    return report, error_message


def _write_failure_stderr(server_err: str, *, verbose: bool, has_auth_hint: bool) -> None:
    """Write appropriate stderr output for a failed inspection."""
    if not server_err:
        sys.stderr.write(
            "Hint: if the server writes logs to stdout, it can break MCP stdio. Ensure server logs go to stderr.\n"
        )
        return

    # By default, keep output clean for auth-required failures:
    # full stderr is available via --verbose.
    # For non-auth failures, print stderr by default to aid debugging.
    if verbose or not has_auth_hint:
        sys.stderr.write("\n[server stderr]\n" + server_err + "\n")


def _emit_report(report: dict, *, save_path: Path | None, as_json: bool) -> None:
    """Save and/or print the JSON report."""
    if save_path:
        save_path.write_text(_report_json(report), encoding="utf-8")
    if as_json:
        sys.stdout.write(_report_json(report))


def main() -> None:
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
        sys.stdout.write(diff_reports(before, after))
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
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        help="Add/override an environment variable for the server (repeatable, KEY=VALUE)",
    )
    parser.add_argument("--cwd", type=Path, help="Working directory for the server process")
    parser.add_argument(
        "--home",
        type=Path,
        help="Set HOME for the server (also sets XDG_* dirs); equivalent to --env HOME=... with extras",
    )
    parser.add_argument(
        "--isolate-home",
        action="store_true",
        help="Run server with HOME (and XDG_* dirs) set to a temporary directory",
    )
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

    server_env, temp_home_ctx = _build_server_env(ns)

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
                timeout_s=ns.timeout,
                errlog=errlog,
                env=server_env,
                cwd=ns.cwd,
                include_signals=not ns.no_signals,
            )
        )

        server_err = _read_captured_stderr(errbuf)
        _postprocess_success(report, server_err, verbose=ns.verbose)

        if not ns.as_json:
            print_text_report(report)
    except BaseException as e:
        server_err = _read_captured_stderr(errbuf)
        _, stderr_flags = stderr_notes(server_err) if server_err else ([], {})
        _write_failure_stderr(
            server_err, verbose=ns.verbose, has_auth_hint=stderr_flags.get("has_auth_hint", False)
        )

        report, error_message = _handle_inspect_failure(
            e, server_err=server_err, command=command, args=args, timeout_s=ns.timeout
        )
        _emit_report(report, save_path=ns.save, as_json=ns.as_json)
        sys.stderr.write(error_message + "\n")
        raise SystemExit(1)
    finally:
        try:
            errlog.close()
        except Exception:
            pass
        try:
            if temp_home_ctx is not None:
                temp_home_ctx.cleanup()
        except Exception:
            pass

    _emit_report(report, save_path=ns.save, as_json=ns.as_json)


if __name__ == "__main__":
    main()