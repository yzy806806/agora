"""Workspace REST API — file endpoints (write/read/delete/stat + Range).

Phase 14.3a: Implements Part D.1 of DESIGN-phase14-workspace.md:
  POST   /workspaces/{project_id}/files/{path:path}  → write
  GET    /workspaces/{project_id}/files/{path:path}  → read (Range support)
  DELETE /workspaces/{project_id}/files/{path:path}  → delete
  HEAD   /workspaces/{project_id}/files/{path:path}  → stat
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response

from ..rbac import Permission, Role, get_current_role, requires
from .manager import WorkspaceManager
from .workspace_router_helpers import _extract_agent_id, parse_range_header

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

# Module-level singleton — set by init_workspace_router_deps()
_ws_manager: Optional[WorkspaceManager] = None


def init_workspace_router_deps(ws_manager: WorkspaceManager) -> None:
    """Initialize workspace manager. Called once at app startup."""
    global _ws_manager
    _ws_manager = ws_manager


def _get_ws() -> WorkspaceManager:
    if _ws_manager is None:
        raise HTTPException(status_code=503, detail="Workspace not initialized")
    return _ws_manager


@router.post(
    "/{project_id}/files/{path:path}", status_code=201,
)
@requires(Permission.WORKSPACE_WRITE)
async def write_file(
    project_id: str, path: str,
    request: Request,
    lock_id: Optional[str] = None,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Create or overwrite a file. Raw bytes body."""
    agent_id = _extract_agent_id(request)
    content = await request.body()
    content_type = request.headers.get("content-type", "application/octet-stream")
    ws = _get_ws()
    try:
        node = await ws.write_file(
            project_id, path, content, agent_id, content_type,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return node.model_dump(mode="json")
