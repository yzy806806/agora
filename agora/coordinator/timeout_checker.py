"""Heartbeat timeout checker background task (Phase 9.3c).

Periodically checks for agents whose last_seen_at exceeds
the timeout threshold and marks them offline.
"""
from __future__ import annotations

import asyncio
import logging

from .models import MessageType
from .storage import Storage

logger = logging.getLogger(__name__)


async def heartbeat_timeout_checker(
    storage: Storage,
    interval: int = 15,
    timeout: int = 120,
    tenant_id: str = "default",
) -> None:
    """Background task: check for stale agents and mark offline.

    Runs forever. Checks every `interval` seconds.
    If an agent hasn't sent HEARTBEAT in `timeout` seconds,
    mark offline.
    """
    while True:
        try:
            stale = await storage.list_stale_agents(
                timeout_seconds=timeout,
            )
            for agent in stale:
                agent_id = agent["agent_id"]
                logger.warning(
                    "Agent %s heartbeat timeout (last seen %s), "
                    "marking offline",
                    agent_id, agent.get("last_seen_at"),
                )
                await storage.set_agent_online(agent_id, False)
        except Exception:
            logger.exception("Heartbeat timeout checker error")
        await asyncio.sleep(interval)
