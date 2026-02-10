from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from conftest import TOY_DIR, parse_preflight_json, run_preflight_json


def test_toy_open_end_to_end_enumerates_and_classifies_risk() -> None:
    report = parse_preflight_json([sys.executable, str(TOY_DIR / "toy_open.py")])
    assert report["server"]["name"] == "toy-open"
    assert report["status"] == "ok"

    tool_names = [t["name"] for t in report["tools"]]
    assert "get_item" in tool_names
    assert "create_item" in tool_names
    assert "delete_item" in tool_names

    # At least: get_item/list_items (read), create_item/frobnicate (write), delete_item (destructive)
    risk = report["risk"]
    assert risk["read"] >= 1
    assert risk["write"] >= 1
    assert risk["destructive"] >= 1

    # Resources + resource templates should both show up.
    assert "toy://items" in report["resources"]
    assert any("{item_id}" in uri for uri in report["resourceTemplates"])

    # Prompt should enumerate with args.
    prompt_names = [p["name"] for p in report["prompts"]]
    assert "analyze_items" in prompt_names


def test_toy_open_capabilities_reports_all_true() -> None:
    report = parse_preflight_json([sys.executable, str(TOY_DIR / "toy_open.py")])
    caps = report["capabilities"]
    assert caps["tools"] is True
    assert caps["resources"] is True
    assert caps["prompts"] is True


def test_toy_auth_gated_without_token_sets_auth_gated_status() -> None:
    report = parse_preflight_json([sys.executable, str(TOY_DIR / "toy_auth_gated.py")])
    assert report["server"]["name"] == "toy-auth-gated"
    assert report["status"] == "auth_gated"
    assert report["tools"] == []
    assert report["resources"] == []
    assert report["resourceTemplates"] == []
    assert report["prompts"] == []


def test_toy_auth_gated_with_token_enumerates() -> None:
    report = parse_preflight_json(
        ["--env", "TOY_TOKEN=ok", sys.executable, str(TOY_DIR / "toy_auth_gated.py")]
    )
    assert report["server"]["name"] == "toy-auth-gated"
    assert report["status"] == "ok"
    assert any(t["name"] == "get_item" for t in report["tools"])


def test_toy_home_aware_custom_home_flag() -> None:
    with tempfile.TemporaryDirectory() as td:
        custom_home = Path(td) / "custom-home"
        custom_home.mkdir(parents=True, exist_ok=True)
        report = parse_preflight_json(
            ["--home", str(custom_home), sys.executable, str(TOY_DIR / "toy_home_aware.py")]
        )
        tool_names = [t["name"] for t in report["tools"]]
        assert "home_custom_flag" in tool_names


def test_toy_home_aware_isolate_home_flag() -> None:
    report = parse_preflight_json(
        ["--isolate-home", sys.executable, str(TOY_DIR / "toy_home_aware.py")]
    )
    tool_names = [t["name"] for t in report["tools"]]
    assert "home_isolated_flag" in tool_names


def test_toy_partial_resources_timeout_sets_partial_status_and_note() -> None:
    report = parse_preflight_json(
        ["--timeout", "0.8", sys.executable, str(TOY_DIR / "toy_partial_resources.py")]
    )
    assert report["server"]["name"] == "toy-partial-resources"
    assert report["status"] == "partial"
    assert any(t["name"] == "ping" for t in report["tools"])
    assert any(
        n.get("kind") == "mcp" and n.get("name") == "list_resources" and n.get("rule") == "timeout"
        for n in (report.get("notes") or [])
    )


# ── Tools-only server (capability-aware) ─────────────────────


def test_toy_tools_only_status_is_ok_not_partial() -> None:
    """A tools-only server should be 'ok', not 'partial' from unsupported capabilities."""
    report = parse_preflight_json([sys.executable, str(TOY_DIR / "toy_tools_only.py")])
    assert report["server"]["name"] == "toy-tools-only"
    assert report["status"] == "ok"


def test_toy_tools_only_capabilities_reflect_server() -> None:
    report = parse_preflight_json([sys.executable, str(TOY_DIR / "toy_tools_only.py")])
    caps = report["capabilities"]
    assert caps["tools"] is True
    assert caps["resources"] is False
    assert caps["prompts"] is False


def test_toy_tools_only_no_spurious_notes() -> None:
    """No error/timeout notes should be generated for unsupported capabilities."""
    report = parse_preflight_json([sys.executable, str(TOY_DIR / "toy_tools_only.py")])
    mcp_notes = [n for n in report.get("notes", []) if n.get("kind") == "mcp"]
    assert mcp_notes == []


def test_toy_tools_only_enumerates_tools() -> None:
    report = parse_preflight_json([sys.executable, str(TOY_DIR / "toy_tools_only.py")])
    tool_names = [t["name"] for t in report["tools"]]
    assert "greet" in tool_names
    assert "get_time" in tool_names
    assert report["resources"] == []
    assert report["resourceTemplates"] == []
    assert report["prompts"] == []


def test_toy_tools_only_text_output_shows_not_supported() -> None:
    """Text mode should say 'not supported by server' for resources/prompts."""
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_preflight", sys.executable, str(TOY_DIR / "toy_tools_only.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    assert "not supported by server" in proc.stdout
    # Should NOT show partial status or error notes.
    assert "partial" not in proc.stdout
    assert "introspection failed" not in proc.stdout

