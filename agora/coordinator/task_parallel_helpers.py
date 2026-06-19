"""Helper utilities for parallel execution (Phase 10).

Phase 16.10: hub parameter is now optional (None).
"""
from __future__ import annotations

import logging
from typing import Any

from .task_models import TaskNode

logger = logging.getLogger(__name__)


def priority_value(task: TaskNode) -> int:
    """Convert task priority to int for PriorityQueue (lower = higher)."""
    order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
    return order.get(getattr(task, "priority", "normal"), 2)


async def pick_agent(
    task: TaskNode, storage: Any, hub: Any = None,
    agent_slots: dict[str, int] | None = None,
) -> str | None:
    """Find an agent with a free slot matching capabilities."""
    if agent_slots is None:
        agent_slots = {}
    from .task_assign import _find_capable_agents
    candidates = await _find_capable_agents(
        task.required_capabilities, storage, hub,
    )
    for c in candidates:
        aid = c["agent_id"]
        free = agent_slots.get(aid, 0)
        if free <= 0:
            max_c = c.get("max_concurrent_tasks", 2)
            count = await storage.get_agent_task_count(aid, active_only=True)
            agent_slots[aid] = max_c - count
        if agent_slots.get(aid, 0) > 0:
            return aid
    return None


async def acquire_resources(
    task_id: str, paths: list[str], resource_tracker: Any,
) -> bool:
    """Acquire locks for all artifact paths. Returns False if blocked."""
    for path in paths:
        ok = await resource_tracker.acquire(task_id, path, "write")
        if not ok:
            for prev in paths:
                if prev == path:
                    break
                await resource_tracker.release(task_id, prev)
            return False
    return True


async def release_resources(
    task_id: str, resource_tracker: Any,
) -> None:
    """Release all resource locks held by a task."""
    unblocked = resource_tracker.release_all(task_id)
