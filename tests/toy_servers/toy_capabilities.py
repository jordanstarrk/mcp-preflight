"""
Toy MCP server modeled after a complex real-world server (GitScrum-scale).

29 tools, 150+ dispatched operations, mix of action/report dispatch keys,
single-purpose auth tools, and a full ://mcp/manifest resource.
"""

from __future__ import annotations

import json

import anyio
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="toy-capabilities", instructions="Toy server with capabilities manifest.")

# ── Manifest ─────────────────────────────────────────────────

MANIFEST_PAYLOAD = {
    "version": "1.0.6",
    "tools": {
        # ── Authentication (single-purpose) ──────────────────
        "auth_login": {
            "description": "Initiate login via device code flow",
            "annotations": {"readOnlyHint": False},
        },
        "auth_complete": {
            "description": "Complete login with device code",
            "annotations": {"readOnlyHint": False},
        },
        "auth_status": {
            "description": "Check current authentication status",
            "annotations": {"readOnlyHint": True},
        },
        "auth_logout": {
            "description": "Clear saved credentials",
            "annotations": {"readOnlyHint": False},
        },
        # ── Tasks ────────────────────────────────────────────
        "task": {
            "description": "Task management and operations",
            "dispatch_key": "action",
            "operations": [
                "my", "today", "notifications", "get", "create", "update",
                "complete", "subtasks", "filter", "by_code", "duplicate", "move",
            ],
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
        },
        # ── Projects & Workspaces ────────────────────────────
        "workspace": {
            "description": "Workspace listing and details",
            "dispatch_key": "action",
            "operations": ["list", "get"],
            "annotations": {"readOnlyHint": True},
        },
        "project": {
            "description": "Project management and details",
            "dispatch_key": "action",
            "operations": [
                "list", "get", "stats", "tasks", "workflows",
                "types", "efforts", "labels", "members",
            ],
            "annotations": {"readOnlyHint": True},
        },
        # ── Sprints ──────────────────────────────────────────
        "sprint": {
            "description": "Sprint planning and tracking",
            "dispatch_key": "action",
            "operations": [
                "list", "all", "get", "kpis", "create", "update",
                "stats", "reports", "progress", "metrics",
            ],
            "annotations": {"readOnlyHint": False},
        },
        # ── User Stories ─────────────────────────────────────
        "user_story": {
            "description": "User story management",
            "dispatch_key": "action",
            "operations": ["list", "get", "create", "update", "all"],
            "annotations": {"readOnlyHint": False},
        },
        # ── Epics ────────────────────────────────────────────
        "epic": {
            "description": "Epic management",
            "dispatch_key": "action",
            "operations": ["list", "create", "update"],
            "annotations": {"readOnlyHint": False},
        },
        # ── Labels ───────────────────────────────────────────
        "label": {
            "description": "Label management",
            "dispatch_key": "action",
            "operations": ["list", "create", "update", "attach", "detach", "toggle"],
            "annotations": {"readOnlyHint": False},
        },
        # ── Task Types ───────────────────────────────────────
        "task_type": {
            "description": "Task type configuration",
            "dispatch_key": "action",
            "operations": ["list", "create", "update", "assign"],
            "annotations": {"readOnlyHint": False},
        },
        # ── Workflows ────────────────────────────────────────
        "workflow": {
            "description": "Kanban column management",
            "dispatch_key": "action",
            "operations": ["create", "update"],
            "annotations": {"readOnlyHint": False},
        },
        # ── Time Tracking ────────────────────────────────────
        "time": {
            "description": "Time tracking and analytics",
            "dispatch_key": "action",
            "operations": [
                "active", "start", "stop", "logs", "analytics",
                "team", "reports", "productivity", "timeline",
            ],
            "annotations": {"readOnlyHint": False},
        },
        # ── Wiki ─────────────────────────────────────────────
        "wiki": {
            "description": "Wiki page management",
            "dispatch_key": "action",
            "operations": ["list", "get", "create", "update", "search"],
            "annotations": {"readOnlyHint": False},
        },
        # ── Search (single-purpose) ──────────────────────────
        "search": {
            "description": "Global search across tasks, projects, stories, and wiki",
            "annotations": {"readOnlyHint": True},
        },
        # ── Comments ─────────────────────────────────────────
        "comment": {
            "description": "Task comment management",
            "dispatch_key": "action",
            "operations": ["list", "add", "update"],
            "annotations": {"readOnlyHint": False},
        },
        # ── NoteVault ────────────────────────────────────────
        "note": {
            "description": "Note management",
            "dispatch_key": "action",
            "operations": ["list", "get", "create", "update", "share", "revisions"],
            "annotations": {"readOnlyHint": False},
        },
        "note_folder": {
            "description": "Note folder organization",
            "dispatch_key": "action",
            "operations": ["list", "create", "update", "move"],
            "annotations": {"readOnlyHint": False},
        },
        # ── ClientFlow CRM ───────────────────────────────────
        "client": {
            "description": "Client management",
            "dispatch_key": "action",
            "operations": ["list", "get", "stats", "create", "update"],
            "annotations": {"readOnlyHint": False},
        },
        "invoice": {
            "description": "Invoice management",
            "dispatch_key": "action",
            "operations": [
                "list", "get", "stats", "create", "update",
                "issue", "send", "mark_paid",
            ],
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
        },
        "proposal": {
            "description": "Proposal management",
            "dispatch_key": "action",
            "operations": [
                "list", "get", "stats", "create", "send",
                "approve", "reject", "convert",
            ],
            "annotations": {"readOnlyHint": False},
        },
        "clientflow_dashboard": {
            "description": "ClientFlow executive dashboard",
            "dispatch_key": "report",
            "operations": [
                "overview", "revenue", "at_risk", "pending",
                "health", "insights", "leaderboard", "analytics",
            ],
            "annotations": {"readOnlyHint": True},
        },
        "clientflow_cross_workspace": {
            "description": "Cross-workspace ClientFlow data",
            "dispatch_key": "report",
            "operations": ["invoices", "proposals", "clients", "change_requests"],
            "annotations": {"readOnlyHint": True},
        },
        # ── Team Standup (PRO) ───────────────────────────────
        "standup": {
            "description": "Team standup reports and blockers",
            "dispatch_key": "action",
            "operations": [
                "summary", "completed", "blockers", "team",
                "stuck", "digest", "contributors",
            ],
            "annotations": {"readOnlyHint": True},
        },
        # ── Analytics & Manager Dashboard (PRO) ──────────────
        "analytics": {
            "description": "Workspace analytics and manager dashboard",
            "dispatch_key": "report",
            "operations": [
                "pulse", "risks", "flow", "age", "activity",
                "overview", "health", "blockers", "command_center", "time_entries",
            ],
            "annotations": {"readOnlyHint": True},
        },
        # ── Discussions ──────────────────────────────────────
        "discussion": {
            "description": "Team discussions and channels",
            "dispatch_key": "action",
            "operations": [
                "all", "channels", "channel", "messages", "send",
                "search", "unread", "mark_read", "create_channel", "update_channel",
            ],
            "annotations": {"readOnlyHint": False},
        },
        # ── Activity Feed ────────────────────────────────────
        "activity": {
            "description": "Activity feed and notifications",
            "dispatch_key": "action",
            "operations": ["feed", "user_feed", "notifications", "activities", "task_workflow"],
            "annotations": {"readOnlyHint": True},
        },
        # ── Budget Tracking (PRO) ────────────────────────────
        "budget": {
            "description": "Budget tracking and alerts",
            "dispatch_key": "action",
            "operations": [
                "projects_at_risk", "overview", "consumption",
                "burn_down", "alerts", "events",
            ],
            "annotations": {"readOnlyHint": True},
        },
    },
}


# ── Resources ────────────────────────────────────────────────

@mcp.resource("toy://mcp/manifest", description="Server capabilities manifest")
def manifest() -> str:
    return json.dumps(MANIFEST_PAYLOAD)


@mcp.resource("toy://readme", description="Getting started guide")
def readme() -> str:
    return "Hello from toy-capabilities"


# ── Auth tools (single-purpose) ──────────────────────────────

@mcp.tool(description="Initiate login via device code flow")
def auth_login() -> str:
    return "ok"


@mcp.tool(description="Complete login with device code")
def auth_complete(device_code: str = "") -> str:
    return "ok"


@mcp.tool(description="Check current authentication status")
def auth_status() -> str:
    return "ok"


@mcp.tool(description="Clear saved credentials")
def auth_logout() -> str:
    return "ok"


# ── Dispatch tools (action-based) ────────────────────────────

@mcp.tool(description="Task management and operations")
def task(action: str, **kwargs: str) -> str:
    return f"task:{action}"


@mcp.tool(description="Workspace listing and details")
def workspace(action: str) -> str:
    return f"workspace:{action}"


@mcp.tool(description="Project management and details")
def project(action: str) -> str:
    return f"project:{action}"


@mcp.tool(description="Sprint planning and tracking")
def sprint(action: str) -> str:
    return f"sprint:{action}"


@mcp.tool(description="User story management")
def user_story(action: str) -> str:
    return f"user_story:{action}"


@mcp.tool(description="Epic management")
def epic(action: str) -> str:
    return f"epic:{action}"


@mcp.tool(description="Label management")
def label(action: str) -> str:
    return f"label:{action}"


@mcp.tool(description="Task type configuration")
def task_type(action: str) -> str:
    return f"task_type:{action}"


@mcp.tool(description="Kanban column management")
def workflow(action: str) -> str:
    return f"workflow:{action}"


@mcp.tool(description="Time tracking and analytics")
def time(action: str) -> str:
    return f"time:{action}"


@mcp.tool(description="Wiki page management")
def wiki(action: str) -> str:
    return f"wiki:{action}"


@mcp.tool(description="Global search across tasks, projects, stories, and wiki")
def search(query: str) -> str:
    return f"search:{query}"


@mcp.tool(description="Task comment management")
def comment(action: str) -> str:
    return f"comment:{action}"


@mcp.tool(description="Note management")
def note(action: str) -> str:
    return f"note:{action}"


@mcp.tool(description="Note folder organization")
def note_folder(action: str) -> str:
    return f"note_folder:{action}"


@mcp.tool(description="Client management")
def client(action: str) -> str:
    return f"client:{action}"


@mcp.tool(description="Invoice management")
def invoice(action: str) -> str:
    return f"invoice:{action}"


@mcp.tool(description="Proposal management")
def proposal(action: str) -> str:
    return f"proposal:{action}"


# ── Dispatch tools (report-based) ────────────────────────────

@mcp.tool(description="ClientFlow executive dashboard")
def clientflow_dashboard(report: str) -> str:
    return f"clientflow_dashboard:{report}"


@mcp.tool(description="Cross-workspace ClientFlow data")
def clientflow_cross_workspace(report: str) -> str:
    return f"clientflow_cross_workspace:{report}"


@mcp.tool(description="Team standup reports and blockers")
def standup(action: str) -> str:
    return f"standup:{action}"


@mcp.tool(description="Workspace analytics and manager dashboard")
def analytics(report: str) -> str:
    return f"analytics:{report}"


@mcp.tool(description="Team discussions and channels")
def discussion(action: str) -> str:
    return f"discussion:{action}"


@mcp.tool(description="Activity feed and notifications")
def activity(action: str) -> str:
    return f"activity:{action}"


@mcp.tool(description="Budget tracking and alerts")
def budget(action: str) -> str:
    return f"budget:{action}"


# ── Entry point ──────────────────────────────────────────────

def main() -> None:
    anyio.run(mcp.run_stdio_async)


if __name__ == "__main__":
    main()
