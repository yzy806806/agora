"""Agent-related MCP tools: register_agent, update_status."""
from __future__ import annotations

import logging
import secrets
import uuid

from pydantic import BaseModel, Field

from ..deps import get_storage
from ..server import mcp_server

logger = logging.getLogger(__name__)


class RegisterAgentResult(BaseModel):
    agent_id: str
    agent_token: str
    approval_status: str
    registration_token: str = ""


@mcp_server.tool()
async def register_agent(
    name: str,
    capabilities: list[str] | None = None,
    agent_type: str = "hermes",
    metadata: dict | None = None,
) -> dict:
    """Register this agent with Agora.

    Returns agent_id and token for future authentication.
    """
    storage = get_storage()
    agent_id = f"agent-{uuid.uuid4().hex[:8]}"
    agent_token = f"ag-{secrets.token_hex(16)}"
    reg_token = f"reg-{secrets.token_hex(12)}"

    from agora.coordinator.config import settings as _settings
    is_approved = not _settings.require_approval
    approval_status = "auto_approved" if is_approved else "pending"

    result = await storage.register_agent(
        agent_id=agent_id,
        name=name,
        capabilities=capabilities,
        agent_type=agent_type,
        agent_token=agent_token,
        is_approved=is_approved,
        approval_status=approval_status,
        registration_token=reg_token,
    )
    return {
        "agent_id": result["agent_id"],
        "agent_token": result["agent_token"],
        "approval_status": result["approval_status"],
        "registration_token": reg_token,
    }


@mcp_server.tool()
async def update_status(
    status: str,
    load: float = 0.0,
) -> dict:
    """Update this agent's status (online, busy, idle, offline)."""
    valid = {"online", "busy", "idle", "offline"}
    if status not in valid:
        return {"error": f"Invalid status '{status}'. Must be one of {valid}"}

    storage = get_storage()
    online = status != "offline"

    # Use heartbeat to update status
    await storage.update_agent_heartbeat(
        agent_id=_get_current_agent_id(),
        load=load,
    )
    await storage.set_agent_online(
        agent_id=_get_current_agent_id(),
        online=online,
    )
    return {"status": status, "updated_at": "now"}


def _get_current_agent_id() -> str:
    """Extract agent_id from MCP context."""
    try:
        ctx = mcp_server.get_context()
        request = ctx.request_context.request
        aid = getattr(request.state, "mcp_agent_id", None)
        return aid or "unknown"
    except Exception:
        return "unknown"
