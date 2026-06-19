"""Task Assigner — capability matching and round-robin assignment.

Phase 16.10: hub parameter is now optional (None). Agent communication
uses MCP notifications instead of WebSocket. When hub is None, task
assignment notifications are delivered via MCPNotificationBridge.
"""
from __future__ import annotations

import logging
from typing import Any

from .task_models import TaskGraph, TaskNode, TaskStatus

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENT = 5


def capability_match_score(
    agent_caps: list[str], required_caps: list[str],
) -> float:
    """Score how well agent capabilities match requirements (0.0–1.0)."""
    if not required_caps:
        return 0.5
    return len(set(agent_caps) & set(required_caps)) / len(required_caps)


async def _find_capable_agents(
    required_caps: list[str], storage: Any, hub: Any = None,
) -> list[dict]:
    """Find agents matching required capabilities, sorted by score.

    When hub is provided and has get_online_agents(), filters by
    online status. Otherwise, considers all registered agents.
    """
    online_ids: set[str] | None = None
    if hub is not None and hasattr(hub, "get_online_agents"):
        online_ids = set(hub.get_online_agents())
    all_agents = await storage.list_agents(online_only=False)
    scored: list[tuple[float, dict]] = []
    for agent in all_agents:
        if online_ids is not None and agent["agent_id"] not in online_ids:
            continue
        caps = agent.get("capabilities") or []
        if isinstance(caps, str):
            import json
            caps = json.loads(caps)
        score = capability_match_score(caps, required_caps)
        if score > 0:
            scored.append((score, agent))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored]


def _round_robin_pick(
    candidates: list[dict],
    agent_loads: dict[str, int],
    max_concurrent: dict[str, int],
    rr_index: list[int],
) -> str | None:
    """Pick next agent via round-robin, skipping those at capacity."""
    if not candidates:
        return None
    n = len(candidates)
    for _ in range(n):
        idx = rr_index[0] % n
        rr_index[0] += 1
        agent = candidates[idx]
        aid = agent["agent_id"]
        load = agent_loads.get(aid, 0)
        cap = max_concurrent.get(aid, DEFAULT_MAX_CONCURRENT)
        if load < cap:
            return aid
    return None


async def _notify_task_assignment(
    task: TaskNode, agent_id: str, hub: Any = None,
) -> bool:
    """Send task assignment notification to agent.

    Uses MCP notification bridge when hub is None.
    Falls back to hub.send() when hub is provided (legacy).
    """
    msg = {
        "type": "TASK_ASSIGNED",
        "task_id": task.id,
        "graph_id": task.graph_id,
        "title": task.title,
        "description": task.description,
        "required_capabilities": task.required_capabilities,
        "depends_on": task.depends_on,
        "workspace_paths": task.workspace_paths,
    }
    if hub is not None and hasattr(hub, "send"):
        return await hub.send(agent_id, msg)
    # MCP notification path
    try:
        from .event_bus import publish
        await publish("TASK_ASSIGNED", {
            "task_id": task.id,
            "agent_id": agent_id,
            "title": task.title,
        }, channel="tasks")
    except Exception:
        logger.warning("MCP task assignment notification failed for %s", agent_id)
    return True


async def assign_tasks(
    graph: TaskGraph, storage: Any, hub: Any = None,
) -> dict[str, str]:
    """Assign all PENDING tasks in a graph to capable agents.

    Returns {task_id: agent_id} mapping.
    """
    assignments: dict[str, str] = {}
    done_ids: set[str] = set()
    agent_loads: dict[str, int] = {}
    rr_index = [0]

    status_map: dict[str, TaskStatus] = {}
    for t in graph.tasks:
        status_map[t.id] = t.status
        if t.status in (TaskStatus.DONE, TaskStatus.ACCEPTED):
            done_ids.add(t.id)

    pending = [t for t in graph.tasks if t.status == TaskStatus.PENDING]

    def _deps_ready(task: TaskNode) -> bool:
        return all(d in done_ids for d in task.depends_on)

    remaining = list(pending)
    while remaining:
        ready = [t for t in remaining if _deps_ready(t)]
        if not ready:
            logger.warning(
                "%d tasks blocked by unmet dependencies", len(remaining)
            )
            break
        for task in ready:
            candidates = await _find_capable_agents(
                task.required_capabilities, storage, hub,
            )
            for c in candidates:
                aid = c["agent_id"]
                if aid not in agent_loads:
                    agent_loads[aid] = await storage.get_agent_task_count(
                        aid, active_only=True,
                    )
            picked = _round_robin_pick(
                candidates, agent_loads, {}, rr_index,
            )
            if picked is None:
                logger.warning(
                    "No capable agent for task %s", task.id,
                )
                continue
            await storage.update_task_status(
                task.id, TaskStatus.ASSIGNED.value, assigned_to=picked,
            )
            task.status = TaskStatus.ASSIGNED
            task.assigned_to = picked
            await _notify_task_assignment(task, picked, hub)
            agent_loads[picked] = agent_loads.get(picked, 0) + 1
            assignments[task.id] = picked
        done_ids.update(t.id for t in ready)
        remaining = [t for t in remaining if t not in ready]

    return assignments


async def reassign_task(
    task_id: str, storage: Any, hub: Any = None,
    agent_slots: dict[str, int] | None = None,
) -> str | None:
    """Re-assign a task to a different agent (dynamic re-assignment).

    Returns the new agent_id or None if no agent available.
    """
    task = await storage.get_task(task_id)
    if not task:
        logger.warning("Reassign: task %s not found", task_id)
        return None
    old_agent = task.get("assigned_to")
    candidates = await _find_capable_agents(
        task.get("required_capabilities", []), storage, hub,
    )
    if agent_slots is None:
        agent_slots = {}
    rr_index = [0]
    picked = _round_robin_pick(candidates, agent_slots, {}, rr_index)
    if picked is None or picked == old_agent:
        return None
    await storage.update_task_status(
        task_id, TaskStatus.ASSIGNED.value, assigned_to=picked,
    )
    node = TaskNode(
        id=task_id, graph_id=task.get("graph_id", ""),
        motion_id=task.get("motion_id", ""),
        title=task.get("title", ""),
        description=task.get("description", ""),
        required_capabilities=task.get("required_capabilities", []),
        depends_on=task.get("depends_on", []),
        workspace_paths=task.get("workspace_paths", []),
    )
    await _notify_task_assignment(node, picked, hub)
    logger.info("Reassigned task %s from %s to %s", task_id, old_agent, picked)
    return picked
