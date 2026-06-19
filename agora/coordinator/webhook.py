"""Webhook CRUD + trigger REST API (consolidated).

POST   /webhooks                    — Register
GET    /webhooks                    — List
GET    /webhooks/{id}               — Get
PUT    /webhooks/{id}               — Update
DELETE /webhooks/{id}               — Delete
POST   /webhooks/{id}/trigger       — Trigger
GET    /webhooks/{id}/history       — Trigger history
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .rbac import Permission, Role, get_current_role, requires
from .storage import Storage

logger = logging.getLogger(__name__)

# ---- Models ----

class WebhookConfig(BaseModel):
    """Registered webhook endpoint configuration."""
    id: str
    project_id: str
    name: str
    description: str = ""
    secret_hash: str = ""
    events: list[str] = Field(default_factory=lambda: ["push"])
    enabled: bool = True
    pipeline_template: dict = Field(default_factory=dict)
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat())
    last_triggered_at: Optional[str] = None
    trigger_count: int = 0
    failure_count: int = 0


class WebhookEvent(BaseModel):
    """Incoming webhook payload."""
    webhook_id: str
    event: str
    payload: dict
    headers: dict
    signature: str = ""
    source_ip: str = ""


class WebhookTriggerHistory(BaseModel):
    """Record of a webhook trigger attempt."""
    id: int | None = None
    webhook_id: str
    event: str
    success: bool
    pipeline_id: Optional[str] = None
    error: Optional[str] = None
    source_ip: Optional[str] = None
    triggered_at: datetime = Field(default_factory=datetime.utcnow)


class WebhookRegisterRequest(BaseModel):
    """Request body for POST /api/v1/webhooks."""
    project_id: str
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    secret: str = ""
    events: list[str] = Field(default_factory=lambda: ["push"])
    enabled: bool = True


class WebhookUpdateRequest(BaseModel):
    """Request body for PUT /api/v1/webhooks/{id}."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    secret: Optional[str] = None
    events: Optional[list[str]] = None
    enabled: Optional[bool] = None


# ---- Executor ----

class WebhookPipelineError(Exception):
    """Pipeline creation failed during webhook execution."""


async def execute_webhook(
    webhook: WebhookConfig, event: WebhookEvent, storage: Any,
) -> dict:
    """Create pipeline from event payload."""
    idea = event.payload.get("idea", "Webhook-triggered pipeline")
    project_id = event.payload.get("project_id", webhook.project_id)
    try:
        row = await storage.create_pipeline_run(
            project_id=project_id, idea=idea)
    except Exception as exc:
        logger.error("Pipeline creation failed for webhook %s: %s",
                     webhook.id, exc)
        raise WebhookPipelineError(str(exc)) from exc
    metadata = event.payload.get("metadata", {})
    metadata["webhook_id"] = webhook.id
    metadata["source"] = "webhook"
    return {"pipeline_id": row.get("id"), "project_id": project_id,
            "idea": idea, "metadata": metadata}


# ---- Helpers ----

def _store_secret(secret: str) -> str:
    return secret


async def _get_webhook_or_404(storage: Storage, wh_id: str) -> dict:
    from .storage.webhooks import get_webhook
    async with storage._connection() as db:
        wh = await get_webhook(db, storage.dialect, wh_id)
    if wh is None:
        raise HTTPException(404, detail="Webhook not found")
    return wh


# ---- CRUD Router ----

crud_router = APIRouter()
_storage: Optional[Storage] = None


def init_webhook_router_deps(storage: Storage) -> None:
    global _storage
    _storage = storage


def _s() -> Storage:
    if _storage is None:
        raise HTTPException(503, detail="Not initialized")
    return _storage


@crud_router.post("/webhooks")
@requires(Permission.ADMIN_FULL)
async def create_webhook(
    body: WebhookRegisterRequest,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    from .storage.webhooks import create_webhook as _create
    secret_hash = body.secret
    async with _s()._connection() as db:
        row = await _create(
            db, _s().dialect, project_id=body.project_id,
            name=body.name, secret_hash=secret_hash,
            pipeline_template={}, description=body.description,
            events=body.events, enabled=body.enabled)
    return row


@crud_router.get("/webhooks")
@requires(Permission.CONFIG_READ)
async def list_webhooks(
    project_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    from .storage.webhooks import list_webhooks as _list
    async with _s()._connection() as db:
        items = await _list(
            db, _s().dialect, project_id=project_id,
            limit=limit, offset=offset)
    return {"webhooks": items, "count": len(items)}


@crud_router.get("/webhooks/{webhook_id}")
@requires(Permission.CONFIG_READ)
async def get_webhook(
    webhook_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    return await _get_webhook_or_404(_s(), webhook_id)


@crud_router.put("/webhooks/{webhook_id}")
@requires(Permission.ADMIN_FULL)
async def update_webhook(
    webhook_id: str, body: WebhookUpdateRequest,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    await _get_webhook_or_404(_s(), webhook_id)
    from .storage.webhooks import update_webhook as _update
    updates = body.model_dump(exclude_none=True)
    if "secret" in updates:
        updates["secret_hash"] = updates.pop("secret")
    if not updates:
        raise HTTPException(400, detail="No fields to update")
    async with _s()._connection() as db:
        row = await _update(db, _s().dialect, webhook_id, updates)
    if row is None:
        raise HTTPException(404, detail="Webhook not found")
    return row


@crud_router.delete("/webhooks/{webhook_id}")
@requires(Permission.ADMIN_FULL)
async def delete_webhook(
    webhook_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    from .storage.webhooks import delete_webhook as _del
    async with _s()._connection() as db:
        ok = await _del(db, _s().dialect, webhook_id)
    if not ok:
        raise HTTPException(404, detail="Webhook not found")
    return {"deleted": True, "id": webhook_id}


# ---- Trigger Router ----

trigger_router = APIRouter()
_trigger_storage: Optional[Storage] = None


def init_webhook_trigger_deps(storage: Storage) -> None:
    global _trigger_storage
    _trigger_storage = storage


@trigger_router.post("/webhooks/{webhook_id}/trigger")
async def trigger_webhook(webhook_id: str, request: Request) -> dict:
    if _trigger_storage is None:
        raise HTTPException(503, detail="Not initialized")
    wh = await _get_webhook_or_404(_trigger_storage, webhook_id)
    if not wh.get("enabled", True):
        raise HTTPException(403, detail="Webhook is disabled")
    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {"raw": body.decode(errors="replace")}
    event_type = payload.get("event", "push")
    client_ip = request.client.host if request.client else "0.0.0.0"
    wh_config = WebhookConfig(**wh)
    wh_event = WebhookEvent(
        webhook_id=webhook_id, event=event_type,
        payload=payload, headers=dict(request.headers),
        signature="", source_ip=client_ip)
    try:
        result = await execute_webhook(wh_config, wh_event, _trigger_storage)
    except WebhookPipelineError as exc:
        await _record_trigger(
            _trigger_storage, webhook_id, event_type, False,
            error=str(exc), ip=client_ip)
        raise HTTPException(500, detail=str(exc))
    await _record_trigger(
        _trigger_storage, webhook_id, event_type, True,
        pipeline_id=result.get("pipeline_id"), ip=client_ip)
    return {"status": "accepted", **result}


@trigger_router.get("/webhooks/{webhook_id}/history")
async def get_trigger_history(webhook_id: str) -> dict:
    if _trigger_storage is None:
        raise HTTPException(503, detail="Not initialized")
    await _get_webhook_or_404(_trigger_storage, webhook_id)
    items = await _trigger_storage.list_webhook_history(webhook_id)
    return {"history": items, "count": len(items)}


async def _record_trigger(
    storage: Storage, webhook_id: str, event: str,
    success: bool, pipeline_id: str | None = None,
    error: str | None = None, ip: str | None = None,
) -> None:
    try:
        await storage.record_webhook_trigger(
            webhook_id, event, success,
            pipeline_id=pipeline_id, error=error, source_ip=ip)
    except Exception:
        logger.warning("Failed to record trigger history", exc_info=True)


# Backward compat aliases
router = crud_router
from typing import Any
