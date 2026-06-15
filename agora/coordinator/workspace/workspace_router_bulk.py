"""Workspace REST API — bulk pull/push endpoints (Phase 14.3c).

Implements Part D.1 of DESIGN-phase14-workspace.md:
  POST /workspaces/{project_id}/pull → bulk read
  POST /workspaces/{project_id}/push → bulk write
"""
from __future__ import annotations

import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..rbac import Permission, Role, get_current_role, requires
from .workspace_router import _get_ws
from .workspace_router_helpers import _extract_agent_id

logger = logging.getLogger(__name__)

router_bulk = APIRouter(prefix="/workspaces", tags=["workspaces"])


class PullRequest(BaseModel):
    """Request body for bulk pull."""
    paths: list[str] = Field(..., min_length=1)


class PushFile(BaseModel):
    """Single file entry for bulk push (base64-encoded content)."""
    content_b64: str


class PushRequest(BaseModel):
    """Request body for bulk push."""
    files: dict[str, PushFile] = Field(..., min_length=1)
    lock_ids: Optional[dict[str, str]] = None


@router_bulk.post("/{project_id}/pull")
@requires(Permission.WORKSPACE_WRITE)
async def bulk_pull(
    project_id: str, body: PullRequest, request: Request,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Batch read files. Returns base64-encoded content per path."""
    agent_id = _extract_agent_id(request)
    ws = _get_ws()
    raw = await ws.pull_files(project_id, body.paths, agent_id)
    # Encode bytes → base64 strings for JSON transport
    return {
        "files": {
            p: base64.b64encode(data).decode() for p, data in raw.items()
        },
    }


@router_bulk.post("/{project_id}/push")
@requires(Permission.WORKSPACE_WRITE)
async def bulk_push(
    project_id: str, body: PushRequest, request: Request,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Batch write files (base64-encoded content). Atomic on lock failure."""
    agent_id = _extract_agent_id(request)
    ws = _get_ws()
    files = {
        p: base64.b64decode(entry.content_b64)
        for p, entry in body.files.items()
    }
    try:
        nodes = await ws.push_files(
            project_id, files, agent_id, body.lock_ids,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"files": [n.model_dump(mode="json") for n in nodes]}
