"""MCP Resource: agora://conversations/{conv_id}/messages

Returns message history for a discussion/conversation as JSON.
Maps conversation_id to motion_id in Agora's data model.
"""
from __future__ import annotations

import json
import logging

from ..deps import get_storage
from ..server import mcp_server

logger = logging.getLogger(__name__)


@mcp_server.resource(
    "agora://conversations/{conv_id}/messages",
    name="conversation-messages",
    title="Conversation Messages",
    description="Message history for a discussion/conversation.",
    mime_type="application/json",
)
async def get_conversation_messages(conv_id: str) -> str:
    """Read messages for a conversation (motion)."""
    storage = get_storage()
    # Verify the motion exists
    motion = await storage.get_motion(conv_id)
    if motion is None:
        return json.dumps(
            {"error": "Conversation not found", "conv_id": conv_id}
        )
    messages = await storage.get_messages(conv_id)
    # Strip internal fields, keep MCP-relevant ones
    result = []
    for msg in messages:
        result.append({
            "message_id": msg.get("id"),
            "agent_id": msg.get("agent_id"),
            "content": msg.get("content"),
            "stance": msg.get("stance"),
            "round_num": msg.get("round_num"),
            "timestamp": msg.get("timestamp"),
        })
    return json.dumps(result, default=str)
