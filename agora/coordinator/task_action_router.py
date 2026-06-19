"""Task claim/complete REST endpoints — Phase 15 Part D.

D.1: POST /api/v1/tasks/{id}/claim
D.2: POST /api/v1/tasks/{id}/complete

These endpoints let agents claim and complete tasks via REST API
instead of only through WebSocket messages.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .dashboard_models import TaskDetailResponse
from .rbac import Permission, Role, get_current_role, requires
from .storage import Storage

logger = logging.getLogger(__name__)

router = APIRouter()

_storage: Optional[Storage] = None


def init_task_action_deps(storage: Storage) -> None:
    """Set storage reference. Called from main.py at startup."""
    global _storage
    _storage = storage


def _get_storage() -> Storage:
    if _storage is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return _storage


class TaskClaimRequest(BaseModel):
    """Request body for claiming a task."""
    agent_id: str


class TaskCompleteRequest(BaseModel):
    """Request body for completing a task."""
    agent_id: str
    result: Optional[str] = None
    error: Optional[str] = None
    artifact_paths: list[str] = Field(default_factory=list)


@router.post("/tasks/{task_id}/claim", response_model=TaskDetailResponse)
@requires(Permission.TASK_EXECUTE)
async def claim_task(
    task_id: str,
    request: TaskClaimRequest,
    _rbac_role: Role | None = Depends(get_current_role),
) -> TaskDetailResponse:
    """Agent claims a pending/assigned task.

    Transitions task from pending→assigned, sets assigned_to.
    Broadcasts TASK_ASSIGNED notification via WS.
    """
    storage = _get_storage()
    task = await storage.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] not in ("pending", "assigned"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot claim task in status '{task['status']}'",
        )
    if task.get("assigned_to") and task["assigned_to"] != request.agent_id:
        raise HTTPException(
            status_code=409,
            detail=f"Task already assigned to '{task['assigned_to']}'",
        )
    await storage.update_task_status(
        task_id, "assigned", assigned_to=request.agent_id,
    )
    # Dashboard event bus
    from .event_bus import publish
    await publish("TASK_ASSIGNED", {
        "task_id": task_id, "status": "assigned",
        "agent_id": request.agent_id,
        "motion_id": task.get("motion_id"),
        "title": task.get("title", ""),
        "description": task.get("description", ""),
        "priority": task.get("priority", 0),
    }, channel="tasks")
    updated = await storage.get_task(task_id)
    assert updated is not None
    return TaskDetailResponse(**{str(k): v for k, v in updated.items()})


@router.post("/tasks/{task_id}/complete", response_model=TaskDetailResponse)
@requires(Permission.TASK_EXECUTE)
async def complete_task(
    task_id: str,
    request: TaskCompleteRequest,
    _rbac_role: Role | None = Depends(get_current_role),
) -> TaskDetailResponse:
    """Agent marks a task as done or failed.

    Transitions task: running→done (success) or running→failed (error).
    Broadcasts TASK_COMPLETED/TASK_FAILED notification via WS.
    """
    storage = _get_storage()
    task = await storage.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] not in ("running", "assigned"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot complete task in status '{task['status']}'",
        )
    if task.get("assigned_to") and task["assigned_to"] != request.agent_id:
        raise HTTPException(
            status_code=403,
            detail="Only the assigned agent can complete this task",
        )
    # Determine final status
    if request.error:
        new_status = "failed"
    else:
        new_status = "done"
    await storage.update_task_status(
        task_id, new_status,
        error_message=request.error,
        artifact_paths=request.artifact_paths or None,
    )
    # Dashboard event bus
    from .event_bus import publish
    await publish("TASK_STATUS", {
        "task_id": task_id, "status": new_status,
        "old_status": task["status"],
        "agent_id": request.agent_id,
        "motion_id": task.get("motion_id"),
    }, channel="tasks")
    updated = await storage.get_task(task_id)
    assert updated is not None
    return TaskDetailResponse(**{str(k): v for k, v in updated.items()})
