"""Parallel execution dispatch logic (Phase 10)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .task_models import TaskNode, TaskStatus
from .task_parallel_helpers import pick_agent, priority_value, acquire_resources

logger = logging.getLogger(__name__)


async def dispatch_ready(
    graph_tasks: dict[str, TaskNode], runqueue: asyncio.PriorityQueue,
    storage: Any, hub: Any, agent_slots: dict[str, int],
    resource_tracker: Any, result: dict,
    running_futures: dict[str, asyncio.Task],
) -> None:
    """Assign ready tasks to agents with free slots."""
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
    hub: Any,
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


async def _run_task(task: TaskNode, agent_id: str, hub: Any) -> str:
    """Send task assignment to agent via WebSocket."""
    await hub.send(agent_id, {
        "type": "TASK_ASSIGNED", "task_id": task.id,
        "graph_id": task.graph_id, "title": task.title,
        "workspace_paths": task.workspace_paths})
    return task.id
