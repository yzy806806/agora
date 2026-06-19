"""WS message helpers for workspace file/lock events.

Broadcasts workspace change notifications to dashboard clients
via the DashboardHub. MCP notifications handle agent-side delivery.
"""
from __future__ import annotations

import logging
from typing import Any

from ..models import MessageType

logger = logging.getLogger(__name__)


async def _do_broadcast(message: dict[str, Any]) -> None:
    """Broadcast to dashboard clients; log warning if not wired."""
    from ..dashboard_ws import dashboard_hub
    event_type = message.get("type", "WORKSPACE_EVENT")
    payload = message.get("payload", {})
    try:
        await dashboard_hub.broadcast_event(event_type, payload)
    except Exception:
        logger.warning("Dashboard broadcast failed", exc_info=True)


async def emit_file_changed(
    project_id: str, path: str,
    agent_id: str, version: int,
) -> None:
    """Broadcast WORKSPACE_FILE_CHANGED to dashboard clients."""
    await _do_broadcast({
        "type": MessageType.WORKSPACE_FILE_CHANGED,
        "payload": {
            "project_id": project_id,
            "path": path,
            "agent_id": agent_id,
            "version": version,
        },
    })


async def emit_file_deleted(
    project_id: str, path: str, agent_id: str,
) -> None:
    """Broadcast WORKSPACE_FILE_CHANGED (deleted) to dashboard clients."""
    await _do_broadcast({
        "type": MessageType.WORKSPACE_FILE_CHANGED,
        "payload": {
            "project_id": project_id,
            "path": path,
            "agent_id": agent_id,
            "action": "deleted",
        },
    })


async def emit_lock_acquired(
    project_id: str, path: str,
    lock_type: str, held_by: str,
) -> None:
    """Broadcast WORKSPACE_LOCK_ACQUIRED."""
    await _do_broadcast({
        "type": MessageType.WORKSPACE_LOCK_ACQUIRED,
        "payload": {
            "project_id": project_id,
            "path": path,
            "lock_type": lock_type,
            "held_by": held_by,
        },
    })


async def emit_lock_released(
    project_id: str, path: str, held_by: str,
) -> None:
    """Broadcast WORKSPACE_LOCK_RELEASED."""
    await _do_broadcast({
        "type": MessageType.WORKSPACE_LOCK_RELEASED,
        "payload": {
            "project_id": project_id,
            "path": path,
            "held_by": held_by,
        },
    })


async def emit_lock_expired(
    lock_id: str, path: str, project_id: str,
) -> None:
    """Broadcast WORKSPACE_LOCK_EXPIRED to lock holder."""
    await _do_broadcast({
        "type": MessageType.WORKSPACE_LOCK_EXPIRED,
        "payload": {
            "lock_id": lock_id,
            "path": path,
            "project_id": project_id,
        },
    })
