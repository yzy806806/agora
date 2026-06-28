"""MCP Resource: agora://projects/{project_id}/context

Lightweight project context for session restore — summaries + entry URIs.
Agent reads this first, then fetches details via sub-resources or tools
only for items it actually needs.

Design principle: this resource MUST stay under ~2K tokens even for
long-running projects. It provides the "map", not the "territory".
"""
from __future__ import annotations

import json
import logging

from ..deps import get_storage
from ..server import mcp_server

logger = logging.getLogger(__name__)

# Strict limits to keep output small
_RECENT = 5  # max items per list


@mcp_server.resource(
    "agora://projects/{project_id}/context",
    name="project-context",
    title="Project Context",
    description=(
        "Lightweight project context for session restore: counts, "
        "recent items, and URIs to fetch details on demand. "
        "Stays under ~2K tokens regardless of project size."
    ),
    mime_type="application/json",
)
async def get_project_context(project_id: str) -> str:
    """Return lightweight project context — the map, not the territory."""
    storage = get_storage()

    # --- Recent items (lightweight, limit=5 each) ---
    recent_pending = await storage.list_tasks(status="pending", limit=_RECENT)
    recent_running = await storage.list_tasks(status="running", limit=_RECENT)
    recent_done = await storage.list_tasks(status="done", limit=_RECENT)
    recent_failed = await storage.list_tasks(status="failed", limit=_RECENT)

    # --- Active discussions ---
    try:
        all_motions = await storage.list_motions(limit=20)
    except Exception:
        all_motions = []

    active = []
    for m in all_motions:
        if m.get("status") in ("discussing", "voting"):
            active.append({
                "id": m.get("id"),
                "title": m.get("title"),
                "status": m.get("status"),
                "round": m.get("current_round"),
                "uri": f"agora://conversations/{m.get('id')}/messages",
            })
            if len(active) >= _RECENT:
                break

    # --- Online agents ---
    try:
        agents = await storage.list_agents(online_only=True)
    except Exception:
        agents = []
    online_names = [a.get("name", a.get("id")) for a in agents[:5]]

    # --- Assemble ---
    context = {
        "project_id": project_id,
        "summary": {
            "pending": len(recent_pending),
            "running": len(recent_running),
            "done": len(recent_done),
            "failed": len(recent_failed),
            "active_discussions": len(active),
            "online_agents": len(online_names),
        },
        "recent": {
            "pending_tasks": _trim(recent_pending),
            "running_tasks": _trim(recent_running),
            "active_discussions": active,
        },
        "fetch_more": {
            "tasks": "Use get_pending_tasks tool with status_filter",
            "task_detail": "agora://tasks/{task_id}",
            "discussion_messages": "agora://conversations/{conv_id}/messages",
            "project_overview": "agora://projects/{project_id}/overview",
        },
        "online_agents": online_names,
    }
    return json.dumps(context, default=str)


def _trim(tasks: list[dict]) -> list[dict]:
    """Keep only the fields an agent needs to decide what to pick up."""
    return [
        {
            "id": t.get("id"),
            "title": t.get("title", ""),
            "assigned_to": t.get("assigned_to"),
        }
        for t in tasks[:_RECENT]
    ]
