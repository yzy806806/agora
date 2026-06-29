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
    Also registers the current MCP session with the new agent_id
    so subsequent tool calls can identify this agent.

    If an agent with the same name already exists, reuses that agent_id
    and token (idempotent re-registration for reconnections).
    """
    storage = get_storage()

    from agora.coordinator.config import settings as _settings
    is_approved = not _settings.require_approval
    approval_status = "approved" if is_approved else "pending"

    # Check if an agent with this name already exists (reconnection scenario)
    existing = await storage.find_agent_by_name(name)
    if existing:
        agent_id = existing["agent_id"]
        agent_token = existing["agent_token"]
        reg_token = existing.get("registration_token", "")
        logger.info("Agent %s reconnected (agent_id=%s)", name, agent_id)

        # Update capabilities if provided
        if capabilities:
            await storage.update_agent_config(
                agent_id=agent_id,
                capabilities=capabilities,
            )

        # Update matrix_user_id if provided in metadata
        matrix_user_id = (metadata or {}).get("matrix_user_id", "")
        if matrix_user_id:
            await storage.update_agent_config(
                agent_id=agent_id,
                matrix_user_id=matrix_user_id,
            )
            logger.info("Updated matrix_user_id for agent %s: %s", agent_id, matrix_user_id)

        # Mark agent as online
        await storage.set_agent_online(agent_id=agent_id, online=True)
    else:
        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        agent_token = f"ag-{secrets.token_hex(16)}"
        reg_token = f"reg-{secrets.token_hex(12)}"

        result = await storage.register_agent(
            agent_id=agent_id,
            name=name,
            capabilities=capabilities,
            agent_type=agent_type,
            agent_token=agent_token,
            is_approved=is_approved,
            approval_status=approval_status,
            registration_token=reg_token,
            matrix_user_id=(metadata or {}).get("matrix_user_id", ""),
        )
        logger.info("Agent %s registered as %s", name, agent_id)

    # Register this MCP session with the agent_id
    # so fetch_pending_notifications etc. can find it
    try:
        ctx = mcp_server.get_context()
        request = ctx.request_context.request
        mcp_sid = request.headers.get("mcp-session-id")
        if mcp_sid:
            from ..deps import get_session_map
            try:
                sm = get_session_map()
                sm.register(agent_id, mcp_sid)
                logger.info("Registered session: agent=%s sid=%s", agent_id, mcp_sid)
            except RuntimeError:
                pass
        else:
            logger.warning("No mcp-session-id header in register_agent request")
    except Exception as exc:
        logger.warning("Failed to register MCP session: %s", exc)

    return {
        "agent_id": agent_id,
        "agent_token": agent_token,
        "approval_status": approval_status if not existing else existing.get("approval_status", approval_status),
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
    """Extract agent_id from MCP context.

    Tries request.state first (set by auth middleware).
    Falls back to session_map lookup by MCP session ID.
    """
    try:
        ctx = mcp_server.get_context()
        request = ctx.request_context.request
        aid = getattr(request.state, "mcp_agent_id", None)
        if aid:
            return aid
        # Fallback: look up by MCP session ID
        mcp_sid = request.headers.get("mcp-session-id")
        if mcp_sid:
            try:
                from ..deps import get_session_map
                sm = get_session_map()
                looked_up = sm.get_agent_id(mcp_sid)
                if looked_up:
                    return looked_up
            except RuntimeError:
                pass
        return "unknown"
    except Exception:
        return "unknown"
