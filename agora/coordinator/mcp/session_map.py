"""MCP session mapping: agent_id -> mcp_session_id.

Phase 16.4b: Maintains an in-memory mapping from Agora agent_id
to MCP session IDs. This mapping is established during MCP tool
calls (when the SDK provides the session context) and used by
MCPNotificationBridge to route notifications.

For persistence across restarts, sessions are also stored in
the mcp_sessions DB table (see storage_mcp.py).
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class MCPSessionMap:
    """Bidirectional mapping between agent_id and mcp_session_id.

    The primary direction is agent_id -> mcp_session_id, used to
    find which MCP session to push notifications to.

    The reverse direction (mcp_session_id -> agent_id) is used
    during cleanup / disconnect to remove stale entries.
    """

    def __init__(self) -> None:
        self._agent_to_session: dict[str, str] = {}
        self._session_to_agent: dict[str, str] = {}

    def register(self, agent_id: str, mcp_session_id: str) -> None:
        """Register or update an agent_id -> session mapping.

        If the agent already had a different session, the old
        session mapping is removed (latest session wins).
        """
        old_session = self._agent_to_session.get(agent_id)
        if old_session and old_session != mcp_session_id:
            self._session_to_agent.pop(old_session, None)
            logger.debug(
                "Agent %s session changed: %s -> %s",
                agent_id, old_session, mcp_session_id,
            )
        self._agent_to_session[agent_id] = mcp_session_id
        self._session_to_agent[mcp_session_id] = agent_id

    def unregister_session(self, mcp_session_id: str) -> None:
        """Remove a session mapping (on disconnect)."""
        agent_id = self._session_to_agent.pop(mcp_session_id, None)
        if agent_id:
            # Only remove agent mapping if it still points to
            # this session (not a newer one)
            if self._agent_to_session.get(agent_id) == mcp_session_id:
                del self._agent_to_session[agent_id]

    def get_session_id(self, agent_id: str) -> Optional[str]:
        """Look up mcp_session_id for an agent. None if offline."""
        return self._agent_to_session.get(agent_id)

    def get_agent_id(self, mcp_session_id: str) -> Optional[str]:
        """Look up agent_id for a session. None if unknown."""
        return self._session_to_agent.get(mcp_session_id)

    def is_agent_connected(self, agent_id: str) -> bool:
        """Check if an agent has an active MCP session."""
        return agent_id in self._agent_to_session

    @property
    def connected_agents(self) -> list[str]:
        """List agent_ids with active MCP sessions."""
        return list(self._agent_to_session.keys())

    @property
    def session_count(self) -> int:
        """Number of active MCP sessions."""
        return len(self._session_to_agent)

    def clear(self) -> None:
        """Remove all mappings (for testing / shutdown)."""
        self._agent_to_session.clear()
        self._session_to_agent.clear()
