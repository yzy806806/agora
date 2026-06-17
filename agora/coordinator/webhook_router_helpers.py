"""Webhook route helpers: secret storage, webhook lookup."""
from __future__ import annotations

from fastapi import HTTPException

from .storage import Storage


def store_secret(secret: str) -> str:
    """Store webhook secret for later HMAC verification.

    Phase 14+: stores the raw secret so HMAC-SHA256 verification works
    at trigger time. Encryption-at-rest will be added in a future phase.
    """
    return secret


async def get_webhook_or_404(storage: Storage, wh_id: str) -> dict:
    """Fetch webhook by ID or raise 404."""
    from .storage.webhook_crud import get_webhook
    async with storage._connection() as db:
        wh = await get_webhook(db, storage.dialect, wh_id)
    if wh is None:
        raise HTTPException(404, detail="Webhook not found")
    return wh
