"""Phase 13.4c: Notification REST API routes.

GET  /notifications?project_id=X&unread_only=true&priority=high — list
POST /notifications/{id}/read                                   — mark one read
POST /notifications/read-all  {project_id: "x"}                — mark all read
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .rbac import Permission, Role, get_current_role, requires
from .storage import Storage

logger = logging.getLogger(__name__)

router = APIRouter()

_storage: Optional[Storage] = None


class ReadAllBody(BaseModel):
    """Request body for POST /notifications/read-all."""
    project_id: Optional[str] = None


def init_notification_router_deps(storage: Storage) -> None:
    global _storage
    _storage = storage


@router.get("/notifications")
@requires(Permission.CONFIG_READ)
async def list_notifications(
    project_id: Optional[str] = Query(default=None),
    unread_only: bool = Query(default=False),
    priority: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """List notifications with optional filters."""
    if _storage is None:
        raise HTTPException(status_code=503, detail="Not initialized")
    items = await _storage.list_notifications(
        project_id=project_id,
        unread_only=unread_only,
        priority=priority,
        limit=limit,
        offset=offset,
    )
    total, unread_count = await _storage.count_notifications(
        project_id=project_id,
        unread_only=unread_only,
        priority=priority,
    )
    return {
        "notifications": items,
        "total": total,
        "unread_count": unread_count,
    }


@router.post("/notifications/{notif_id}/read")
@requires(Permission.CONFIG_READ)
async def mark_notification_read(
    notif_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Mark a single notification as read."""
    if _storage is None:
        raise HTTPException(status_code=503, detail="Not initialized")
    result = await _storage.mark_notification_read(notif_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return result


@router.post("/notifications/read-all")
@requires(Permission.CONFIG_READ)
async def mark_all_notifications_read(
    body: ReadAllBody = ReadAllBody(),
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Mark all notifications as read, optionally scoped to a project."""
    if _storage is None:
        raise HTTPException(status_code=503, detail="Not initialized")
    count = await _storage.mark_all_notifications_read(
        project_id=body.project_id,
    )
    return {"marked_count": count}
