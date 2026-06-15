"""Workspace REST API — lock endpoints (acquire, release, check).

Phase 14.3b: Implements Part D.1 of DESIGN-phase14-workspace.md:
  POST   /workspaces/{project_id}/locks             → acquire_lock
  DELETE /workspaces/{project_id}/locks/{lock_id}    → release_lock
  GET    /workspaces/{project_id}/locks?path=        → check_lock
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..rbac import Permission, Role, get_current_role, requires
from .models import LockType
from .workspace_router import _get_ws
from .workspace_router_helpers import _extract_agent_id

logger = logging.getLogger(__name__)

router_locks = APIRouter(prefix="/workspaces", tags=["workspaces"])


class AcquireLockRequest(BaseModel):
    """Request body for acquire_lock endpoint."""
    path: str
    lock_type: LockType
    agent_id: str
    ttl_seconds: int = Field(default=300, ge=10, le=3600)


@router_locks.post("/{project_id}/locks", status_code=201)
@requires(Permission.WORKSPACE_WRITE)
async def acquire_lock(
    project_id: str,
    body: AcquireLockRequest,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Acquire a read or write lock on a file."""
    ws = _get_ws()
    try:
        lock = await ws.locks.acquire_lock(
            project_id=project_id, path=body.path,
            agent_id=body.agent_id, lock_type=body.lock_type,
            ttl_seconds=body.ttl_seconds,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return lock.model_dump(mode="json")


@router_locks.delete("/{project_id}/locks/{lock_id}")
@requires(Permission.WORKSPACE_ADMIN)
async def release_lock(
    project_id: str, lock_id: str,
    agent_id: str = Query(default=""),
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Release a held lock."""
    ws = _get_ws()
    released = await ws.locks.release_lock(lock_id, agent_id)
    if not released:
        raise HTTPException(
            status_code=404, detail="Lock not found or not held by agent")
    return {"status": "released", "lock_id": lock_id}


@router_locks.get("/{project_id}/locks")
@requires(Permission.WORKSPACE_READ)
async def check_lock(
    project_id: str,
    path: str = Query(default=""),
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Check if a file is currently locked."""
    ws = _get_ws()
    lock = await ws.locks.check_lock(project_id, path)
    if lock is None:
        return {"locked": False, "path": path}
    return {"locked": True, **lock.model_dump(mode="json")}
