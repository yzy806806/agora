"""Communication MCP tools: send_message, list_conversations."""
from __future__ import annotations

import logging

from ..deps import get_storage
from ..server import mcp_server

logger = logging.getLogger(__name__)


@mcp_server.tool()
async def send_message(
    conversation_id: str,
    message: str,
    stance: str = "neutral",
) -> dict:
    """Send a message in a discussion/conversation."""
    storage = get_storage()
    agent_id = _get_current_agent_id()

    valid_stances = {"support", "oppose", "neutral"}
    if stance not in valid_stances:
        return {
            "error": f"Invalid stance '{stance}'. Must be one of {valid_stances}",
        }

    # Verify conversation exists
    motion = await storage.get_motion(conversation_id)
    if motion is None:
        return {"error": "Conversation not found", "code": 404}

    # Add message
    round_num = motion.get("current_round", 1)
    msg_id = await storage.add_message(
        motion_id=conversation_id,
        agent_id=agent_id,
        round_num=round_num,
        stance=stance,
        content=message,
    )

    # Notify via event bus
    _notify_discussion_message(conversation_id, agent_id, message)

    from datetime import datetime, timezone
    return {
        "message_id": str(msg_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@mcp_server.tool()
async def list_conversations(
    limit: int = 20,
    status_filter: str = "active",
) -> dict:
    """List conversations this agent is participating in."""
    storage = get_storage()
    agent_id = _get_current_agent_id()

    # List motions, filter by participant
    motions = await storage.list_motions(limit=limit)

    status_map = {"active": "discussing", "closed": "completed", "all": None}
    target_status = status_map.get(status_filter)

    conversations = []
    for m in motions:
        if target_status and m.get("status") != target_status:
            continue
        participants = m.get("participants", [])
        if isinstance(participants, str):
            import json
            try:
                participants = json.loads(participants)
            except (json.JSONDecodeError, TypeError):
                participants = []
        # Include if agent is participant or no filter
        if agent_id in participants or not participants:
            conversations.append({
                "conversation_id": m.get("id", ""),
                "title": m.get("title", ""),
                "status": m.get("status", ""),
                "participant_count": len(participants),
                "last_message_at": m.get("updated_at", ""),
            })

    return {"conversations": conversations[:limit], "total": len(conversations)}


def _get_current_agent_id() -> str:
    """Extract agent_id from MCP context."""
    try:
        ctx = mcp_server.get_context()
        request = ctx.request_context.request
        aid = getattr(request.state, "mcp_agent_id", None)
        return aid or "unknown"
    except Exception:
        return "unknown"


def _notify_discussion_message(conv_id: str, sender_id: str, content: str):
    """Broadcast discussion message via event bus."""
    try:
        from ...event_bus import publish
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(publish("DISCUSSION_MESSAGE", {
                "conversation_id": conv_id,
                "sender_id": sender_id,
                "message": content,
            }, channel="discussions"))
    except Exception as exc:
        logger.debug("Failed to notify discussion message: %s", exc)
