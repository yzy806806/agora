"""Webhook trigger endpoint handlers: trigger + history."""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from .storage import Storage
from .webhook_executor import (
    WebhookPipelineError,
    WebhookRenderError,
    execute_webhook,
)
from .webhook_ip_filter import is_ip_allowed
from .webhook_models import WebhookEvent
from .webhook_rate_limiter import WebhookRateLimiter
from .webhook_router_helpers import get_webhook_or_404
from .webhook_verifier import verify_webhook_request

logger = logging.getLogger(__name__)
router = APIRouter()
_storage: Optional[Storage] = None
_limiter: Optional[WebhookRateLimiter] = None


def init_webhook_trigger_deps(
    storage: Storage, limiter: WebhookRateLimiter,
) -> None:
    global _storage, _limiter
    _storage = storage
    _limiter = limiter


@router.post("/webhooks/{webhook_id}/trigger")
async def trigger_webhook(webhook_id: str, request: Request) -> dict:
    """Trigger a webhook: verify → rate-limit → render → pipeline."""
    if _storage is None or _limiter is None:
        raise HTTPException(503, detail="Not initialized")
    # Load webhook config
    wh = await get_webhook_or_404(_storage, webhook_id)
    if not wh.get("enabled", True):
        raise HTTPException(403, detail="Webhook is disabled")
    # Rate limit
    limit = wh.get("max_triggers_per_hour", 60)
    if not _limiter.check(webhook_id, limit):
        raise HTTPException(429, detail="Rate limit exceeded")
    # IP allowlist
    client_ip = request.client.host if request.client else "0.0.0.0"
    if not is_ip_allowed(client_ip, wh.get("allowed_ips", [])):
        raise HTTPException(403, detail="IP not allowed")
    # Read body + verify signature
    body = await request.body()
    sig = request.headers.get("X-Agora-Signature-256", "")
    ts = request.headers.get("X-Agora-Timestamp", "")
    secret = wh.get("secret_hash", "")
    vr = verify_webhook_request(secret, body, sig, ts)
    if not vr.valid:
        raise HTTPException(401, detail=vr.reason)
    # Parse payload
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {"raw": body.decode(errors="replace")}
    event_type = payload.get("event", "push")
    # Build WebhookEvent + WebhookConfig models
    from .webhook_models import WebhookConfig
    wh_config = WebhookConfig(**wh)
    wh_event = WebhookEvent(
        webhook_id=webhook_id, event=event_type,
        payload=payload, headers=dict(request.headers),
        signature=sig, source_ip=client_ip,
    )
    # Execute: render template + create pipeline
    try:
        result = await execute_webhook(wh_config, wh_event, _storage)
    except WebhookRenderError as exc:
        await _record(_storage, webhook_id, event_type, False,
                       error=str(exc), ip=client_ip)
        raise HTTPException(500, detail=str(exc))
    except WebhookPipelineError as exc:
        await _record(_storage, webhook_id, event_type, False,
                       error=str(exc), ip=client_ip)
        raise HTTPException(500, detail=str(exc))
    # Record success
    await _record(_storage, webhook_id, event_type, True,
                   pipeline_id=result.get("pipeline_id"), ip=client_ip)
    return {"status": "accepted", **result}


async def _record(
    storage: Storage, webhook_id: str, event: str,
    success: bool, pipeline_id: str | None = None,
    error: str | None = None, ip: str | None = None,
) -> None:
    try:
        await storage.record_webhook_trigger(
            webhook_id, event, success,
            pipeline_id=pipeline_id, error=error,
            source_ip=ip,
        )
    except Exception:
        logger.warning("Failed to record trigger history", exc_info=True)


@router.get("/webhooks/{webhook_id}/history")
async def get_trigger_history(webhook_id: str) -> dict:
    """Get trigger history for a webhook."""
    if _storage is None:
        raise HTTPException(503, detail="Not initialized")
    await get_webhook_or_404(_storage, webhook_id)
    items = await _storage.list_webhook_history(webhook_id)
    return {"history": items, "count": len(items)}
