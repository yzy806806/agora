"""Task Execution — state machine and message handlers.

Phase 16.10: hub parameter is now optional (None). Agent communication
uses MCP notifications via event bus instead of WebSocket.
"""
from __future__ import annotations

import logging
from typing import Any

from .models import MessageType

logger = logging.getLogger(__name__)

VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"assigned"},
    "assigned": {"running", "failed"},
    "running": {"done", "failed"},
    "done": {"accepted", "rejected"},
    "rejected": {"pending"},
    "failed": {"pending"},
    "accepted": set(),
}


def _is_valid_transition(current: str, next_status: str) -> bool:
    return next_status in VALID_TRANSITIONS.get(current, set())


async def _send_error(
    hub: Any, agent_id: str, code: str, message: str,
) -> None:
    """Send error notification to agent via event bus or WS hub."""
    if hub is not None and hasattr(hub, "send"):
        await hub.send(agent_id, {
            "type": MessageType.ERROR.value,
            "payload": {"code": code, "message": message},
        })
        return
    # MCP path: publish error event
    try:
        from .event_bus import publish
        await publish("TASK_ERROR", {
            "agent_id": agent_id,
            "code": code,
            "message": message,
        }, channel="tasks")
    except Exception:
        logger.warning("Error notification failed for agent %s", agent_id)


async def handle_task_status(
    agent_id: str,
    payload: dict,
    storage: Any,
    hub: Any = None,
    parallel_coord: Any | None = None,
) -> None:
    """Process TASK_STATUS from an agent."""
    task_id = payload.get("task_id")
    new_status = payload.get("status") or ""
    if not new_status:
        await _send_error(hub, agent_id, "missing_status",
                          "Missing status in payload")
        return
    task = await storage.get_task(task_id)
    if not task:
        await _send_error(hub, agent_id, "task_not_found",
                          f"Task {task_id} not found")
        return
    if not _is_valid_transition(task["status"], new_status):
        await _send_error(hub, agent_id, "invalid_transition",
                          f"Cannot go from {task['status']} to {new_status}")
        return
    await storage.update_task_status(
        task_id, new_status,
        error_message=payload.get("error"),
        artifact_paths=payload.get("artifact_paths"),
    )
    from .event_bus import publish
    await publish("TASK_STATUS", {
        "task_id": task_id, "status": new_status,
        "old_status": task["status"],
        "agent_id": agent_id, "motion_id": task.get("motion_id"),
    }, channel="tasks")
    if new_status == "done":
        from .task_verify import verify_task
        await verify_task(task_id, storage, hub)
        if parallel_coord:
            await _parallel_on_done(
                task_id, task, parallel_coord, storage, hub)
    if new_status == "failed":
        await storage.log_event(
            "task.failed",
            f"Task {task_id} failed: {payload.get('error', '')}",
            motion_id=task["motion_id"],
            agent_id=agent_id,
        )
        if parallel_coord:
            await _parallel_on_fail(
                task_id, task, parallel_coord, storage, hub)


async def handle_task_started(
    agent_id: str, payload: dict, storage: Any, hub: Any = None,
    parallel_coord: Any | None = None,
) -> None:
    """Process TASK_STARTED: agent confirms execution has begun."""
    task_id = payload.get("task_id")
    if not task_id:
        await _send_error(hub, agent_id, "missing_task_id", "Missing task_id")
        return
    task = await storage.get_task(task_id)
    if not task:
        await _send_error(hub, agent_id, "task_not_found", f"Task {task_id} not found")
        return
    await storage.update_task_status(task_id, "running")
    await storage.log_event(
        "task.started", f"Task {task_id} started by {agent_id}",
        motion_id=task["motion_id"], agent_id=agent_id,
    )
    if parallel_coord and task_id in parallel_coord._running_futures:
        parallel_coord.agent_slots[agent_id] = (
            parallel_coord.agent_slots.get(agent_id, 0) - 1)
    logger.info("Task %s started by agent %s", task_id, agent_id)


async def handle_task_progress(
    agent_id: str, payload: dict, storage: Any, hub: Any = None,
) -> None:
    """Process TASK_PROGRESS: optional progress update from agent."""
    task_id = payload.get("task_id")
    if not task_id:
        await _send_error(hub, agent_id, "missing_task_id", "Missing task_id")
        return
    progress_pct = payload.get("progress_pct", 0)
    message = payload.get("message", "")
    await storage.log_event(
        "task.progress",
        f"Task {task_id}: {progress_pct}% — {message}",
        agent_id=agent_id,
    )
    logger.info("Task %s progress: %s%% — %s", task_id, progress_pct, message)


async def handle_task_result(
    agent_id: str, payload: dict, storage: Any, hub: Any = None,
    parallel_coord: Any | None = None,
) -> None:
    """Process TASK_RESULT (Protocol v2): structured task result."""
    from .models import (
        StructuredError, TaskOutput, TaskResult, TaskResultStatus,
    )
    task_id = payload.get("task_id")
    if not task_id:
        await _send_error(hub, agent_id, "missing_task_id", "Missing task_id")
        return
    task = await storage.get_task(task_id)
    if not task:
        await _send_error(hub, agent_id, "task_not_found",
                          f"Task {task_id} not found")
        return
    result_status = payload.get("status", "success")
    try:
        out_data = payload.get("output", {})
        if isinstance(out_data, dict):
            output = TaskOutput(**out_data)
        else:
            output = TaskOutput()
        err_data = payload.get("error")
        error = StructuredError(**err_data) if err_data else None
        tr = TaskResult(
            task_id=task_id,
            status=TaskResultStatus(result_status),
            output=output,
            error=error,
            metrics=payload.get("metrics"),
        )
    except Exception as exc:
        await _send_error(hub, agent_id, "invalid_result",
                          f"Invalid TaskResult: {exc}")
        return
    await storage.save_task_result(task_id, tr.model_dump_json())
    if result_status == "success":
        v1_status = "done"
    elif result_status == "partial":
        v1_status = "done"
    else:
        v1_status = "failed"
    await handle_task_status(
        agent_id,
        {
            "task_id": task_id,
            "status": v1_status,
            "error": (tr.error.message if tr.error else None),
            "artifact_paths": tr.output.artifacts,
        },
        storage, hub, parallel_coord,
    )


async def _parallel_on_done(
    task_id: str, task: dict, coord: Any, storage: Any, hub: Any = None,
) -> None:
    """Release resources and free agent slot on task completion."""
    from .task_parallel_events import on_task_complete
    await on_task_complete(
        task_id, coord._graph_tasks, coord._completed,
        coord._failed, coord._result, coord.agent_slots,
        coord.resource_tracker, coord.runqueue,
    )
    from .task_parallel_dispatch import dispatch_ready
    await dispatch_ready(
        coord._graph_tasks, coord.runqueue, storage, hub,
        coord.agent_slots, coord.resource_tracker,
        coord._result, coord._running_futures,
    )
    logger.info("Parallel: task %s done, resources released", task_id)


async def _parallel_on_fail(
    task_id: str, task: dict, coord: Any, storage: Any, hub: Any = None,
) -> None:
    """Cascade failure to dependents and release agent slot."""
    from .task_parallel_events import on_task_failed
    await on_task_failed(
        task_id, f"Task {task_id} failed", coord._graph_tasks,
        coord._failed, coord._result, coord.agent_slots,
        coord.resource_tracker,
    )
    logger.warning("Parallel: task %s failed, cascading", task_id)


async def execute_task_graph(
    graph: Any, storage: Any, hub: Any = None,
    parallel_coord: Any | None = None,
) -> dict[str, str]:
    """Execute a task graph, delegating to parallel coordinator when needed."""
    mode = getattr(graph, "parallel_mode", "auto")
    if parallel_coord and mode != "sequential":
        logger.info(
            "Executing graph %s via parallel coordinator (mode=%s)",
            graph.id, mode,
        )
        return await parallel_coord.execute_graph(graph)
    from .task_assign import assign_tasks
    return await assign_tasks(graph, storage, hub)
