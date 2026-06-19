"""Heartbeat monitoring for agent connections.

Phase 16.10: Simplified — no WS ConnectionManager dependency.
PING/PONG is handled via REST API or MCP protocol.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class AgentConnectionStatus:
    """Agent connection health status constants."""
    ACTIVE = "active"
    UNRESPONSIVE = "unresponsive"
    OFFLINE = "offline"


class HeartbeatManager:
    """Manages periodic heartbeat tracking for agent connections."""

    def __init__(self, _mgr: object | None = None) -> None:
        # _mgr kept for signature compat but no longer used
        self.pending_pings: dict[str, float] = {}
        self.missed_pings: dict[str, int] = {}
        self._task: asyncio.Task | None = None

    async def start_heartbeat(self, interval: int = 30) -> None:
        """Start periodic heartbeat check task (default 30s)."""
        self._task = asyncio.create_task(self._heartbeat_loop(interval))
        logger.info("Heartbeat started with %ds interval", interval)

    async def _heartbeat_loop(self, interval: int) -> None:
        while True:
            await asyncio.sleep(interval)

    def handle_pong(self, agent_id: str) -> None:
        """Process PONG — clear pending ping, reset miss count."""
        self.pending_pings.pop(agent_id, None)
        self.missed_pings[agent_id] = 0
        logger.debug("PONG received from %s", agent_id)

    def mark_offline(self, agent_id: str) -> None:
        """Mark agent OFFLINE after 3 missed PONGs."""
        self.pending_pings.pop(agent_id, None)
        self.missed_pings[agent_id] = 3
        logger.warning("Agent %s marked OFFLINE", agent_id)

    def get_connection_status(self, agent_id: str) -> str:
        """Return ACTIVE / UNRESPONSIVE / OFFLINE for the agent."""
        missed = self.missed_pings.get(agent_id, 0)
        if missed >= 3:
            return AgentConnectionStatus.OFFLINE
        if missed >= 1:
            return AgentConnectionStatus.UNRESPONSIVE
        return AgentConnectionStatus.ACTIVE

    async def stop(self) -> None:
        """Cancel the heartbeat background task."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("Heartbeat stopped")
