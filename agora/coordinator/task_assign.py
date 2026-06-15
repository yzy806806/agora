"""Task Assigner — capability matching and round-robin assignment."""

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
    required_caps: list[str], storage: Any, hub: Any,
) -> list[dict]:
    """Find online agents matching required capabilities, sorted by score."""
    online_ids = set(hub.get_online_agents())
    all_agents = await storage.list_agents(online_only=False)
    scored: list[tuple[float, dict]] = []
    for agent in all_agents:
        if agent["agent_id"] not in online_ids:
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


async def _send_task_assignment(
    task: TaskNode, agent_id: str, hub: Any,
) -> bool:
    """Send TASK_ASSIGNED WebSocket message to the agent."""
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
    return await hub.send(agent_id, msg)


async def assign_tasks(
    graph: TaskGraph, storage: Any, hub: Any,
) -> dict[str, str]:
    """Assign all PENDING tasks in a graph to capable agents.

    Returns {task_id: agent_id} mapping.
    """
    assignments: dict[str, str] = {}
    done_ids: set[str] = set()
    agent_loads: dict[str, int] = {}
    rr_index = [0]

    # Build status lookup for dependency checks
    status_map: dict[str, TaskStatus] = {}
    for t in graph.tasks:
        status_map[t.id] = t.status
        if t.status in (TaskStatus.DONE, TaskStatus.ACCEPTED):
            done_ids.add(t.id)

    # Sort: tasks with no pending deps first
    pending = [t for t in graph.tasks if t.status == TaskStatus.PENDING]

    def _deps_ready(task: TaskNode) -> bool:
        return all(d in done_ids for d in task.depends_on)

    # Process in dependency order (BFS-like)
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
            # Refresh load for candidates
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
            await _send_task_assignment(task, picked, hub)
            agent_loads[picked] = agent_loads.get(picked, 0) + 1
            assignments[task.id] = picked
        done_ids.update(t.id for t in ready)
        remaining = [t for t in remaining if t not in ready]

    return assignments


async def reassign_task(
    task_id: str, storage: Any, hub: Any,
    agent_slots: dict[str, int] | None = None,
) -> str | None:
    """Re-assign a task to a different agent (dynamic re-assignment).

    Used when an agent finishes early or goes offline, allowing
    the task to be picked up by another available agent.
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
    await _send_task_assignment(node, picked, hub)
    logger.info("Reassigned task %s from %s to %s", task_id, old_agent, picked)
    return picked
