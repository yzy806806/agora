"""MCP Resource: agora://agents/{agent_id}/status

Returns agent status, capabilities, and current load as JSON.
"""
from __future__ import annotations

import json
import logging

from ..deps import get_storage
from ..server import mcp_server

logger = logging.getLogger(__name__)


@mcp_server.resource(
    "agora://agents/{agent_id}/status",
    name="agent-status",
    title="Agent Status",
    description="Agent status, capabilities, and current load.",
    mime_type="application/json",
)
async def get_agent_status_resource(agent_id: str) -> str:
    """Read an agent's status by ID."""
    storage = get_storage()
    agent = await storage.get_agent(agent_id)
    if agent is None:
        return json.dumps(
            {"error": "Agent not found", "agent_id": agent_id}
        )
    # Strip sensitive fields
    agent.pop("agent_token", None)
    agent.pop("registration_token", None)
    return json.dumps(agent, default=str)
