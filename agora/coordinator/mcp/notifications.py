"""MCP Notification Bridge — Phase 16.4a.

Bridges Agora internal EventBus events to MCP client
notifications via SSE. When a task is assigned, a discussion
message arrives, or a task status changes, this bridge
forwards the event to the relevant MCP client sessions.

Architecture:
  Agora event → EventBus → MCPNotificationBridge → session → SSE
"""
from __future__ import annotations

import logging
from typing import Any, Optional, TYPE_CHECKING

from .session_map import MCPSessionMap

if TYPE_CHECKING:
    from ..storage import Storage

logger = logging.getLogger(__name__)


class MCPNotificationBridge:
    """Bridges Agora EventBus events to MCP SSE notifications.

    Uses MCPSessionMap for in-memory agent_id → session mapping.
    Also checks auth.py's mapping as fallback for sessions
    established during MCP tool calls.
    """

    def __init__(
        self,
        session_map: MCPSessionMap,
        storage: Storage,
    ) -> None:
        self._session_map = session_map
        self._storage = storage
        self._mcp_server: Any = None

    def set_mcp_server(self, server: Any) -> None:
        """Set the FastMCP server instance for notifications.

        Called from main.py after MCP server is created.
        If never called, all notification attempts are no-ops.
        """
        self._mcp_server = server

    async def on_task_assigned(
        self, task_id: str, agent_id: str, payload: dict,
    ) -> None:
        """Push task_assigned to target agent's MCP session."""
        await self._send_to_agent(
            agent_id,
            "notifications/task_assigned",
            {"task_id": task_id, **payload},
        )

    async def on_task_updated(
        self, task_id: str, old_status: str,
        new_status: str, agent_id: str,
    ) -> None:
        """Push task_updated to the assigned agent."""
        await self._send_to_agent(
            agent_id,
            "notifications/task_updated",
            {
                "task_id": task_id,
                "old_status": old_status,
                "new_status": new_status,
                "agent_id": agent_id,
            },
        )

    async def on_discussion_message(
        self, conv_id: str, sender_id: str,
        message: str, timestamp: str = "",
    ) -> None:
        """Push discussion_message to participants except sender."""
        participants = await self._get_conversation_participants(
            conv_id,
        )
        for agent_id in participants:
            if agent_id == sender_id:
                continue
            await self._send_to_agent(
                agent_id,
                "notifications/discussion_message",
                {
                    "conversation_id": conv_id,
                    "sender_id": sender_id,
                    "message": message,
                    "timestamp": timestamp,
                },
            )

    async def on_pipeline_event(
        self, pipeline_id: str, stage: str,
        status: str, message: str = "",
    ) -> None:
        """Push pipeline_event to all connected MCP agents."""
        payload = {
            "pipeline_id": pipeline_id,
            "stage": stage,
            "status": status,
            "message": message,
        }
        for agent_id in list(self._get_all_connected_agents()):
            await self._send_to_agent(
                agent_id, "notifications/pipeline_event", payload,
            )

    def _find_session_id(self, agent_id: str) -> Optional[str]:
        """Find MCP session ID for an agent.

        Uses MCPSessionMap as the single source of truth.
        Legacy auth.py fallback removed (consolidated in Phase 16.4b).
        """
        return self._session_map.get_session_id(agent_id)

    def _get_all_connected_agents(self) -> set[str]:
        """Get all agent IDs with active MCP sessions."""
        return set(self._session_map.connected_agents)

    async def _send_to_agent(
        self, agent_id: str, method: str, params: dict,
    ) -> bool:
        """Send a notification to an agent's MCP session.

        If the agent is online, pushes via SSE.
        If offline, queues the notification in DB and tries Telegram wakeup.

        Returns True if sent or queued, False if completely failed.
        """
        session_id = self._find_session_id(agent_id)
        if session_id is not None and self._mcp_server is not None:
            try:
                await self._send_notification(session_id, method, params)
                logger.debug(
                    "Sent %s to agent %s (session %s)",
                    method, agent_id, session_id,
                )
                return True
            except Exception:
                logger.warning(
                    "Failed to send %s to agent %s via SSE, falling back to queue",
                    method, agent_id, exc_info=True,
                )
                # Fall through to queue

        # Agent offline or push failed — queue in DB
        try:
            async with self._storage._connection() as db:
                from ..storage.pending_notifications import add_pending_notification
                notif_id = await add_pending_notification(
                    db, self._storage.dialect,
                    agent_id=agent_id,
                    notification_type=method,
                    payload=params,
                )
                logger.info(
                    "Queued notification %s for offline agent %s (type=%s)",
                    notif_id, agent_id, method,
                )
        except Exception:
            logger.error(
                "Failed to queue notification for agent %s",
                agent_id, exc_info=True,
            )
            return False

        # Try wakeup via configured channels (Telegram and/or Matrix)
        try:
            import asyncio
            asyncio.create_task(
                _try_all_wakeups(self._storage, agent_id, method, params)
            )
        except Exception:
            logger.debug("Wakeup attempt failed for %s", agent_id)

        return True

    async def _send_notification(
        self, session_id: str, method: str, params: dict,
    ) -> None:
        """Send notification via MCP server SDK.

        Integration point for MCP SDK's session notification.
        When Phase 16.1 creates the FastMCP server, it
        exposes active sessions.
        """
        if hasattr(self._mcp_server, "_session_manager"):
            mgr = self._mcp_server._session_manager
            session = mgr.sessions.get(session_id)
            if session:
                await session.send_notification(
                    method=method,
                    params=params,
                )
                return
        logger.debug(
            "MCP server session lookup not available for %s",
            session_id,
        )

    async def _get_conversation_participants(
        self, conv_id: str,
    ) -> list[str]:
        """Get agent IDs participating in a conversation."""
        try:
            messages = await self._storage.get_messages(conv_id)
            participants: set[str] = set()
            for msg in messages:
                aid = msg.get("agent_id")
                if aid:
                    participants.add(aid)
            return list(participants)
        except Exception:
            logger.warning(
                "Failed to get participants for conv %s",
                conv_id, exc_info=True,
            )
            return []


async def _try_all_wakeups(
    storage: Any,
    agent_id: str,
    notification_type: str,
    payload: dict,
) -> None:
    """Try all configured wakeup channels (Telegram + Matrix).

    Fire-and-forget — failures in one channel don't block others.
    """
    # Try Telegram wakeup
    try:
        from ..telegram_wakeup import try_wakeup_agent as try_telegram
        await try_telegram(storage, agent_id, notification_type, payload)
    except Exception:
        logger.debug("Telegram wakeup failed for %s", agent_id, exc_info=True)

    # Try Matrix wakeup
    try:
        from ..matrix_wakeup import try_wakeup_agent as try_matrix
        await try_matrix(storage, agent_id, notification_type, payload)
    except Exception:
        logger.debug("Matrix wakeup failed for %s", agent_id, exc_info=True)
