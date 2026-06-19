"""Task-related MCP tools: get_pending_tasks, accept_task, submit_task_result."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from ..deps import get_storage
from ..server import mcp_server

logger = logging.getLogger(__name__)


@mcp_server.tool()
async def get_pending_tasks(
    limit: int = 20,
    status_filter: str = "all",
) -> dict:
    """Get tasks assigned to or available for this agent."""
    storage = get_storage()
    agent_id = _get_current_agent_id()

    status_map = {
        "pending": "pending",
        "assigned": "assigned",
        "all": None,
    }
    status = status_map.get(status_filter)

    tasks = await storage.list_tasks(
        agent_id=agent_id if status_filter != "pending" else None,
        status=status,
        limit=limit,
    )
    # Also include unassigned pending tasks
    if status_filter in ("pending", "all"):
        unassigned = await storage.list_tasks(
            agent_id=None,
            status="pending",
            limit=limit,
        )
        existing_ids = {t["id"] for t in tasks}
        for t in unassigned:
            if t["id"] not in existing_ids:
                tasks.append(t)

    return {
        "tasks": [
            {
                "task_id": t["id"],
                "title": t.get("title", ""),
                "description": t.get("description", ""),
                "status": t.get("status", ""),
                "assigned_to": t.get("assigned_to"),
                "created_at": t.get("created_at", ""),
                "priority": 0,
                "dependencies": t.get("depends_on", []),
            }
            for t in tasks[:limit]
        ],
        "total": len(tasks),
    }


@mcp_server.tool()
async def accept_task(task_id: str) -> dict:
    """Accept a task assigned to this agent.

    Transitions task from pending/assigned to running.
    """
    storage = get_storage()
    agent_id = _get_current_agent_id()

    task = await storage.get_task(task_id)
    if task is None:
        return {"error": "Task not found", "code": 404}
    if task["status"] not in ("pending", "assigned"):
        return {
            "error": f"Cannot accept task in status '{task['status']}'",
            "code": 409,
        }
    if task.get("assigned_to") and task["assigned_to"] != agent_id:
        return {"error": "Task assigned to different agent", "code": 403}

    await storage.update_task_status(
        task_id, "running",
        assigned_to=agent_id if agent_id else None,
    )
    now = datetime.now(timezone.utc).isoformat()

    # Broadcast via WS if available
    _notify_task_change(task_id, "running", agent_id)

    return {
        "task_id": task_id,
        "status": "running",
        "accepted_at": now,
    }


@mcp_server.tool()
async def submit_task_result(
    task_id: str,
    result: str = "",
    error: str = "",
    artifact_paths: list[str] | None = None,
) -> dict:
    """Submit the result of a completed task."""
    storage = get_storage()
    agent_id = _get_current_agent_id()

    task = await storage.get_task(task_id)
    if task is None:
        return {"error": "Task not found", "code": 404}
    if task["status"] not in ("running", "assigned"):
        return {
            "error": f"Cannot complete task in status '{task['status']}'",
            "code": 409,
        }
    if task.get("assigned_to") and task["assigned_to"] != agent_id:
        return {"error": "Only assigned agent can complete", "code": 403}

    new_status = "failed" if error else "done"
    await storage.update_task_status(
        task_id, new_status,
        error_message=error or None,
        artifact_paths=artifact_paths or None,
    )
    now = datetime.now(timezone.utc).isoformat()

    _notify_task_change(task_id, new_status, agent_id)

    return {
        "task_id": task_id,
        "status": new_status,
        "completed_at": now,
    }


def _get_current_agent_id() -> str | None:
    """Extract agent_id from MCP context."""
    try:
        ctx = mcp_server.get_context()
        request = ctx.request_context.request
        aid = getattr(request.state, "mcp_agent_id", None)
        return aid
    except Exception:
        return None


def _notify_task_change(task_id: str, status: str, agent_id: str | None):
    """Broadcast task status change via event bus."""
    try:
        from ...event_bus import publish
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(publish("TASK_STATUS", {
                "task_id": task_id,
                "status": status,
                "agent_id": agent_id or "unknown",
            }, channel="tasks"))
    except Exception as exc:
        logger.debug("Failed to notify task change: %s", exc)
