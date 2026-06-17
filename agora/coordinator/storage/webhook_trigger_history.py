"""Webhook trigger history CRUD — backend-agnostic.

Split from webhook_crud.py to stay under 80 lines per file.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect
from .webhook_crud import _normalize_webhook

logger = logging.getLogger(__name__)


async def record_trigger(
    db: Any, dialect: Dialect,
    webhook_id: str, event: str, success: bool,
    pipeline_id: str | None = None,
    error: str | None = None,
    source_ip: str | None = None,
) -> dict:
    """Insert a trigger history row and update webhook counters."""
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "webhook_id": webhook_id, "event": event,
        "success": 1 if success else 0,
        "pipeline_id": pipeline_id, "error": error,
        "source_ip": source_ip, "triggered_at": now,
    }
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["?"] * len(row))
    sql, params = dialect.render(
        f"INSERT INTO webhook_trigger_history ({cols}) "
        f"VALUES ({placeholders})", list(row.values()))
    await db.execute(sql, params)
    # Update webhook counters (dialect-aware for Postgres compat)
    if success:
        sql, params = dialect.render(
            "UPDATE webhooks SET trigger_count = trigger_count + 1, "
            "last_triggered_at = ? WHERE id = ?", [now, webhook_id])
        await db.execute(sql, params)
    else:
        sql, params = dialect.render(
            "UPDATE webhooks SET failure_count = failure_count + 1, "
            "last_triggered_at = ? WHERE id = ?", [now, webhook_id])
        await db.execute(sql, params)
    await db.commit()
    row["success"] = success
    row["triggered_at"] = now
    return row


async def list_trigger_history(
    db: Any, dialect: Dialect,
    webhook_id: str,
    limit: int = 100, offset: int = 0,
) -> list[dict]:
    """List trigger history for a webhook."""
    sql, params = dialect.render(
        "SELECT * FROM webhook_trigger_history "
        "WHERE webhook_id = ? ORDER BY triggered_at DESC "
        "LIMIT ? OFFSET ?", [webhook_id, limit, offset])
    async with db.execute(sql, params) as cur:
        rows = [dict(r) async for r in cur]
    for r in rows:
        if "success" in r and isinstance(r["success"], int):
            r["success"] = bool(r["success"])
    return rows
