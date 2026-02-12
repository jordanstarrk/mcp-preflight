from __future__ import annotations

from mcp_preflight import diff_reports


def test_diff_reports_detects_added_removed_and_risk_changes() -> None:
    before = {
        "server": {"name": "s"},
        "risk": {"write": 1, "destructive": 0, "read": 0},
        "tools": [{"name": "t1", "risk": "write"}, {"name": "t2", "risk": "read"}],
        "resources": ["toy://a"],
        "resourceTemplates": ["toy://t/{id}"],
        "prompts": [{"name": "p1"}],
    }
    after = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 1, "read": 0},
        "tools": [{"name": "t1", "risk": "destructive"}, {"name": "t3", "risk": "read"}],
        "resources": ["toy://b"],
        "resourceTemplates": ["toy://t/{id}", "toy://u/{id}"],
        "prompts": [{"name": "p2"}],
    }

    diff = diff_reports(before, after)
    assert "Tools:" in diff
    assert "+ t3" in diff
    assert "- t2" in diff
    assert "~ t1: write -> destructive" in diff
    assert "Resources:" in diff
    assert "+ toy://b" in diff
    assert "- toy://a" in diff
    assert "+ toy://u/{id}" in diff
    assert "Prompts:" in diff
    assert "+ p2" in diff
    assert "- p1" in diff


# ── Manifest / capabilities diffing ─────────────────────────


def test_diff_detects_added_manifest_tool() -> None:
    before = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": [
            {"tool": "task", "operations": ["list", "get"]},
        ],
    }
    after = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": [
            {"tool": "task", "operations": ["list", "get"]},
            {"tool": "budget", "operations": ["overview", "alerts", "burn_down"]},
        ],
    }
    diff = diff_reports(before, after)
    assert "Capabilities:" in diff
    assert "+ budget (3 operations)" in diff


def test_diff_detects_removed_manifest_tool() -> None:
    before = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": [
            {"tool": "task", "operations": ["list", "get"]},
            {"tool": "legacy", "operations": ["run"]},
        ],
    }
    after = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": [
            {"tool": "task", "operations": ["list", "get"]},
        ],
    }
    diff = diff_reports(before, after)
    assert "Capabilities:" in diff
    assert "- legacy (1 operations)" in diff


def test_diff_detects_changed_operations() -> None:
    before = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": [
            {"tool": "invoice", "operations": ["list", "get", "create", "update", "stats"]},
        ],
    }
    after = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": [
            {"tool": "invoice", "operations": ["list", "get", "create", "update", "stats", "issue", "send", "mark_paid"]},
        ],
    }
    diff = diff_reports(before, after)
    assert "Capabilities:" in diff
    assert "~ invoice: 5 operations -> 8 operations" in diff
    assert "added: issue, mark_paid, send" in diff


def test_diff_detects_removed_operations() -> None:
    before = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": [
            {"tool": "task", "operations": ["list", "get", "create", "delete"]},
        ],
    }
    after = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": [
            {"tool": "task", "operations": ["list", "get", "create"]},
        ],
    }
    diff = diff_reports(before, after)
    assert "~ task: 4 operations -> 3 operations" in diff
    assert "removed: delete" in diff


def test_diff_no_manifest_in_either_report_shows_no_capabilities_section() -> None:
    before = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
    }
    after = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
    }
    diff = diff_reports(before, after)
    assert "Capabilities:" not in diff
    assert "No changes detected." in diff


def test_diff_unchanged_manifest_shows_no_capabilities_section() -> None:
    manifest = [
        {"tool": "task", "operations": ["list", "get"]},
        {"tool": "auth_login"},
    ]
    before = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": manifest,
    }
    after = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": manifest,
    }
    diff = diff_reports(before, after)
    assert "Capabilities:" not in diff


def test_diff_single_action_tool_added() -> None:
    before = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": [],
    }
    after = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": [{"tool": "auth_login"}],
    }
    diff = diff_reports(before, after)
    assert "Capabilities (now visible):" in diff
    assert "+ auth_login" in diff
    # Single action tool should not show operation count in its own line
    assert "+ auth_login (" not in diff


def test_diff_before_has_no_manifest_after_does() -> None:
    """Server adds a manifest between scans — all tools show as added."""
    before = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
    }
    after = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": [
            {"tool": "task", "operations": ["list", "get", "create"]},
            {"tool": "auth_login"},
        ],
    }
    diff = diff_reports(before, after)
    assert "Capabilities (now visible):" in diff
    assert "+ task (3 operations)" in diff
    assert "+ auth_login" in diff


def test_diff_before_has_manifest_after_does_not() -> None:
    """Server removes its manifest — all tools show as removed."""
    before = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": [
            {"tool": "invoice", "operations": ["list", "get"]},
        ],
    }
    after = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
    }
    diff = diff_reports(before, after)
    assert "Capabilities:" in diff
    assert "- invoice (2 operations)" in diff


def test_diff_tool_changes_from_dispatched_to_single_action() -> None:
    """Tool drops its operations — effectively goes from dispatched to single."""
    before = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": [{"tool": "task", "operations": ["list", "get"]}],
    }
    after = {
        "server": {"name": "s"},
        "risk": {"write": 0, "destructive": 0, "read": 0},
        "tools": [], "resources": [], "resourceTemplates": [], "prompts": [],
        "manifest": [{"tool": "task"}],
    }
    diff = diff_reports(before, after)
    assert "Capabilities:" in diff
    assert "~ task: 2 operations -> 0 operations" in diff
    assert "removed: get, list" in diff

