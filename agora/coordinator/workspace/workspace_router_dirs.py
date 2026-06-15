"""Workspace REST API — directory endpoints (list_dir, mkdir, rmdir).

Phase 14.3b: Implements Part D.1 of DESIGN-phase14-workspace.md:
  GET    /workspaces/{project_id}/tree?path=&recursive=false → list_dir
  POST   /workspaces/{project_id}/dirs/{path:path}          → mkdir
  DELETE /workspaces/{project_id}/dirs/{path:path}          → rmdir
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from ..rbac import Permission, Role, get_current_role, requires
from .workspace_router import _get_ws
from .workspace_router_helpers import _extract_agent_id

logger = logging.getLogger(__name__)

router_dirs = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router_dirs.get("/{project_id}/tree")
@requires(Permission.WORKSPACE_READ)
async def list_dir(
    project_id: str,
    path: str = Query(default=""),
    recursive: bool = Query(default=False),
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """List directory contents."""
    ws = _get_ws()
    entries = await ws.list_dir(project_id, path, recursive=recursive)
    return {
        "path": path,
        "entries": [e.model_dump(mode="json") for e in entries],
    }


@router_dirs.post("/{project_id}/dirs/{path:path}", status_code=201)
@requires(Permission.WORKSPACE_WRITE)
async def mkdir(
    project_id: str, path: str,
    agent_id: str = "api",
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Create a directory (idempotent — returns existing if present)."""
    ws = _get_ws()
    node = await ws.mkdir(project_id, path, agent_id)
    return node.model_dump(mode="json")


@router_dirs.delete("/{project_id}/dirs/{path:path}")
@requires(Permission.WORKSPACE_ADMIN)
async def rmdir(
    project_id: str, path: str,
    agent_id: str = "api",
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Remove an empty directory."""
    ws = _get_ws()
    try:
        removed = await ws.rmdir(project_id, path, agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(
            status_code=404, detail="Directory not found or not a directory")
    return {"status": "removed", "path": path}
