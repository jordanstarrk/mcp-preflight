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

