"""WS message helpers for workspace file/lock events.

Provides broadcast functions that fan-out workspace change
notifications to all connected agents via the WS hub.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from ..models import MessageType

logger = logging.getLogger(__name__)

# Type: async callable that takes a message dict and returns count
BroadcastFn = Callable[[dict[str, Any]], Awaitable[int]]

# Module-level broadcast function, set during init
_broadcast: BroadcastFn | None = None


def init_ws_messages(broadcast_fn: BroadcastFn) -> None:
    """Wire the WS broadcast function (called from lifespan)."""
    global _broadcast
    _broadcast = broadcast_fn


async def _do_broadcast(message: dict[str, Any]) -> None:
    """Broadcast if wired; log warning otherwise."""
    if _broadcast is None:
        logger.debug("WS broadcast not initialized, skipping event")
        return
    try:
        await _broadcast(message)
    except Exception:
        logger.warning("WS broadcast failed", exc_info=True)


async def emit_file_changed(
    project_id: str, path: str,
    agent_id: str, version: int,
) -> None:
    """Broadcast WORKSPACE_FILE_CHANGED to project agents."""
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
    """Broadcast WORKSPACE_FILE_CHANGED (deleted) to project agents."""
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
