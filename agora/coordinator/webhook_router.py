"""Webhook CRUD REST API routes (Phase 14+ Part D).

POST   /webhooks              — Register a webhook
GET    /webhooks              — List webhooks (optional project_id filter)
GET    /webhooks/{id}         — Get webhook config
PUT    /webhooks/{id}         — Update webhook config
DELETE /webhooks/{id}         — Delete webhook config
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .rbac import Permission, Role, get_current_role, requires
from .storage import Storage
from .webhook_models import (
    WebhookRegisterRequest,
    WebhookUpdateRequest,
)
from .webhook_router_helpers import store_secret, get_webhook_or_404

logger = logging.getLogger(__name__)
router = APIRouter()
_storage: Optional[Storage] = None


def init_webhook_router_deps(storage: Storage) -> None:
    global _storage
    _storage = storage


def _s() -> Storage:
    if _storage is None:
        raise HTTPException(503, detail="Not initialized")
    return _storage


@router.post("/webhooks")
@requires(Permission.ADMIN_FULL)
async def create_webhook(
    body: WebhookRegisterRequest,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Register a new webhook."""
    import json
    from .storage.webhook_crud import create_webhook as _create
    secret_hash = body.secret  # store raw for HMAC verify (D.7)
    template = json.loads(body.pipeline_template)
    async with _s()._connection() as db:
        row = await _create(
            db, _s().dialect,
            project_id=body.project_id,
            name=body.name,
            secret_hash=secret_hash,
            pipeline_template=template,
            description=body.description,
            events=body.events,
            enabled=body.enabled,
        )
    logger.info("Webhook %s registered for project %s",
                row["id"], body.project_id)
    return row


@router.get("/webhooks")
@requires(Permission.CONFIG_READ)
async def list_webhooks(
    project_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """List webhook configurations."""
    from .storage.webhook_crud_extra import list_webhooks as _list
    async with _s()._connection() as db:
        items = await _list(
            db, _s().dialect, project_id=project_id,
            limit=limit, offset=offset)
    return {"webhooks": items, "count": len(items)}


@router.get("/webhooks/{webhook_id}")
@requires(Permission.CONFIG_READ)
async def get_webhook(
    webhook_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Get a single webhook configuration."""
    return await get_webhook_or_404(_s(), webhook_id)


@router.put("/webhooks/{webhook_id}")
@requires(Permission.ADMIN_FULL)
async def update_webhook(
    webhook_id: str,
    body: WebhookUpdateRequest,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Update a webhook configuration."""
    await get_webhook_or_404(_s(), webhook_id)
    from .storage.webhook_crud_extra import update_webhook as _update
    updates = body.model_dump(exclude_none=True)
    if "secret" in updates:
        updates["secret_hash"] = updates.pop("secret")  # raw for HMAC
    if "pipeline_template" in updates:
        import json
        updates["pipeline_template"] = json.loads(updates["pipeline_template"])
    if not updates:
        raise HTTPException(400, detail="No fields to update")
    async with _s()._connection() as db:
        row = await _update(db, _s().dialect, webhook_id, updates)
    if row is None:
        raise HTTPException(404, detail="Webhook not found")
    return row


@router.delete("/webhooks/{webhook_id}")
@requires(Permission.ADMIN_FULL)
async def delete_webhook(
    webhook_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Delete a webhook configuration."""
    from .storage.webhook_crud_extra import delete_webhook as _del
    async with _s()._connection() as db:
        ok = await _del(db, _s().dialect, webhook_id)
    if not ok:
        raise HTTPException(404, detail="Webhook not found")
    return {"deleted": True, "id": webhook_id}
