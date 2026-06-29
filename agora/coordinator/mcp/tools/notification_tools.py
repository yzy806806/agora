"""MCP tools for fetching pending notifications (Phase 19).

These tools allow agents to pull queued notifications when they
come online, rather than relying solely on SSE push.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from ..deps import get_storage
from ..server import mcp_server

logger = logging.getLogger(__name__)


class NotificationItem(BaseModel):
    notif_id: str
    notification_type: str
    payload: dict
    created_at: str


class FetchNotificationsResult(BaseModel):
    notifications: list[dict]
    count: int
    message: str


@mcp_server.tool()
async def fetch_pending_notifications(
    ack: bool = True,
    limit: int = 20,
) -> dict:
    """Fetch pending notifications queued while this agent was offline.

    Call this when starting up to catch up on missed task assignments,
    discussion messages, and pipeline events.

    Args:
        ack: If True, auto-acknowledge notifications after fetching.
        limit: Max notifications to fetch (default 20).
    """
    storage = get_storage()
    agent_id = _get_current_agent_id()

    if agent_id == "unknown":
        return {"error": "Could not determine agent identity", "notifications": []}

    try:
        async with storage._connection() as db:
            from ...storage.pending_notifications import (
                get_pending_notifications,
                mark_notification_delivered,
            )
            notifications = await get_pending_notifications(
                db, storage.dialect, agent_id, limit=limit,
            )

            if ack:
                for n in notifications:
                    await mark_notification_delivered(
                        db, storage.dialect, n["id"],
                    )

        if not notifications:
            return {
                "notifications": [],
                "count": 0,
                "message": "No pending notifications.",
            }

        # Summarize for the agent
        summary_parts = []
        for n in notifications:
            ntype = n["notification_type"]
            if "task_assigned" in ntype:
                title = n["payload"].get("title", n["payload"].get("task_id", "?"))
                summary_parts.append(f"📋 Task: {title}")
            elif "discussion_message" in ntype:
                sender = n["payload"].get("sender_id", "?")
                summary_parts.append(f"💬 Message from {sender}")
            elif "pipeline_event" in ntype:
                stage = n["payload"].get("stage", "?")
                summary_parts.append(f"🔄 Pipeline: {stage}")
            else:
                summary_parts.append(f"📨 {ntype}")

        return {
            "notifications": [
                {
                    "id": n["id"],
                    "type": n["notification_type"],
                    "payload": n["payload"],
                    "created_at": n["created_at"],
                    "acked": ack,
                }
                for n in notifications
            ],
            "count": len(notifications),
            "message": f"Found {len(notifications)} pending notification(s):\n" +
                       "\n".join(f"  {s}" for s in summary_parts),
        }

    except Exception as exc:
        logger.error("fetch_pending_notifications failed: %s", exc, exc_info=True)
        return {"error": str(exc), "notifications": [], "count": 0}


@mcp_server.tool()
async def ack_notification(notif_id: str) -> dict:
    """Acknowledge a specific notification after processing it.

    Args:
        notif_id: The notification ID to acknowledge.
    """
    storage = get_storage()
    try:
        async with storage._connection() as db:
            from ...storage.pending_notifications import mark_notification_acked
            await mark_notification_acked(db, storage.dialect, notif_id)
        return {"status": "acked", "notif_id": notif_id}
    except Exception as exc:
        logger.error("ack_notification failed: %s", exc)
        return {"error": str(exc), "notif_id": notif_id}


@mcp_server.tool()
async def set_telegram_chat_id(chat_id: str) -> dict:
    """Register this agent's Telegram chat ID for wakeup notifications.

    When Agora has new tasks for this agent and it's offline,
    a Telegram message will be sent to this chat ID.

    Args:
        chat_id: Telegram chat ID (numeric string or @username).
    """
    storage = get_storage()
    agent_id = _get_current_agent_id()

    if agent_id == "unknown":
        return {"error": "Could not determine agent identity"}

    try:
        async with storage._connection() as db:
            sql, params = storage.dialect.render(
                "UPDATE agents SET telegram_chat_id = ? WHERE agent_id = ?",
                [chat_id, agent_id],
            )
            await db.execute(sql, params)
            await db.commit()
        return {
            "status": "ok",
            "agent_id": agent_id,
            "telegram_chat_id": chat_id,
            "message": f"Telegram chat ID set for wakeup notifications.",
        }
    except Exception as exc:
        logger.error("set_telegram_chat_id failed: %s", exc)
        return {"error": str(exc)}


def _get_current_agent_id() -> str:
    """Extract agent_id from MCP context.

    Tries:
    1. Auth middleware's mcp_agent_id (from Bearer token)
    2. MCPSessionMap lookup (from mcp-session-id header)
    """
    try:
        ctx = mcp_server.get_context()
        request = ctx.request_context.request
        aid = getattr(request.state, "mcp_agent_id", None)
        if aid and aid != "unknown":
            return aid
    except Exception:
        pass

    # Fallback: try session map from mcp-session-id header
    try:
        ctx = mcp_server.get_context()
        request = ctx.request_context.request
        mcp_sid = request.headers.get("mcp-session-id")
        if mcp_sid:
            from ..deps import get_session_map
            try:
                session_map = get_session_map()
                aid = session_map.get_agent_id(mcp_sid)
                if aid:
                    return aid
            except RuntimeError:
                pass
    except Exception:
        pass

    return "unknown"
