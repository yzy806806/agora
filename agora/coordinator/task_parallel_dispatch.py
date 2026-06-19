"""Parallel execution dispatch logic (Phase 10).

Phase 16.10: hub parameter is now optional (None). Task assignment
notifications use MCP/event bus instead of WebSocket.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .task_models import TaskNode, TaskStatus
from .task_parallel_helpers import pick_agent, priority_value, acquire_resources

logger = logging.getLogger(__name__)


async def dispatch_ready(
    graph_tasks: dict[str, TaskNode], runqueue: asyncio.PriorityQueue,
    storage: Any, hub: Any = None, agent_slots: dict[str, int] | None = None,
    resource_tracker: Any = None, result: dict | None = None,
    running_futures: dict[str, asyncio.Task] | None = None,
) -> None:
    """Assign ready tasks to agents with free slots."""
    if agent_slots is None:
        agent_slots = {}
    if result is None:
        result = {}
    if running_futures is None:
        running_futures = {}
    while not runqueue.empty():
        _, task_id = await runqueue.get()
        task = graph_tasks.get(task_id)
        if not task or task.status != TaskStatus.PENDING:
            continue
        agent_id = await pick_agent(task, storage, hub, agent_slots)
        if not agent_id:
            await runqueue.put((priority_value(task), task_id))
            break
        await assign_task(
            task, agent_id, storage, agent_slots,
            resource_tracker, result, running_futures, hub)


async def assign_task(
    task: TaskNode, agent_id: str, storage: Any,
    agent_slots: dict[str, int], resource_tracker: Any,
    result: dict, running_futures: dict[str, asyncio.Task],
    hub: Any = None,
) -> None:
    """Assign a task to an agent, checking resource conflicts."""
    if task.artifact_paths:
        ok = await acquire_resources(task.id, task.artifact_paths, resource_tracker)
        if not ok:
            result["blocked"].append(task.id)
            return
    task.status = TaskStatus.ASSIGNED
    task.assigned_to = agent_id
    await storage.update_task_status(task.id, "assigned", assigned_to=agent_id)
    agent_slots[agent_id] = agent_slots.get(agent_id, 0) - 1
    running_futures[task.id] = asyncio.create_task(
        _run_task(task, agent_id, hub))


async def _run_task(task: TaskNode, agent_id: str, hub: Any = None) -> str:
    """Send task assignment notification via MCP or WS."""
    if hub is not None and hasattr(hub, "send"):
        await hub.send(agent_id, {
            "type": "TASK_ASSIGNED", "task_id": task.id,
            "graph_id": task.graph_id, "title": task.title,
            "workspace_paths": task.workspace_paths})
    else:
        try:
            from .event_bus import publish
            await publish("TASK_ASSIGNED", {
                "task_id": task.id,
                "agent_id": agent_id,
                "title": task.title,
            }, channel="tasks")
        except Exception:
            logger.warning("MCP task dispatch failed for %s", agent_id)
    return task.id
