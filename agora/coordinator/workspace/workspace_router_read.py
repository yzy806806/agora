"""Workspace REST API — read/delete/stat file endpoints.

Split from workspace_router.py to stay under 80 lines.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response

from ..rbac import Permission, Role, get_current_role, requires
from .workspace_router_helpers import _extract_agent_id, parse_range_header

logger = logging.getLogger(__name__)

# Import the same router and _get_ws from the sibling module
from .workspace_router import _get_ws  # noqa: E402

router_read = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router_read.get("/{project_id}/files/{path:path}")
@requires(Permission.WORKSPACE_READ)
async def read_file(
    project_id: str, path: str,
    request: Request,
    range: Optional[str] = Header(None),
    _rbac_role: Role | None = Depends(get_current_role),
) -> Response:
    """Read file content. Supports Range header for partial reads."""
    agent_id = _extract_agent_id(request)
    ws = _get_ws()
    try:
        node, content = await ws.read_file(project_id, path, agent_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if range is not None:
        offset, length = parse_range_header(range, len(content))
        chunk = await ws.read_file_range(project_id, path, offset, length, agent_id)
        return Response(
            content=chunk, status_code=206,
            headers={
                "Content-Range": f"bytes {offset}-{offset+len(chunk)-1}/{len(content)}",
                "X-Checksum-SHA256": node.checksum_sha256 or "",
                "X-Version": str(node.version),
            },
        )
    return Response(
        content=content,
        headers={
            "X-Checksum-SHA256": node.checksum_sha256 or "",
            "X-Version": str(node.version),
        },
    )


@router_read.delete("/{project_id}/files/{path:path}")
@requires(Permission.WORKSPACE_ADMIN)
async def delete_file(
    project_id: str, path: str,
    request: Request,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Delete a file. Fails if locked by another agent."""
    agent_id = _extract_agent_id(request)
    ws = _get_ws()
    try:
        deleted = await ws.delete_file(project_id, path, agent_id)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found")
    return {"status": "deleted"}


@router_read.head("/{project_id}/files/{path:path}")
@requires(Permission.WORKSPACE_READ)
async def stat_file(
    project_id: str, path: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> Response:
    """Get file metadata without content (HEAD request)."""
    ws = _get_ws()
    node = await ws.stat(project_id, path)
    if node is None:
        raise HTTPException(status_code=404, detail="File not found")
    return Response(
        headers={
            "X-File-Id": node.id,
            "X-Size": str(node.size),
            "X-Content-Type": node.content_type,
            "X-Checksum-SHA256": node.checksum_sha256 or "",
            "X-Version": str(node.version),
            "X-Created-By": node.created_by,
            "X-Updated-At": node.updated_at.isoformat(),
        },
    )
