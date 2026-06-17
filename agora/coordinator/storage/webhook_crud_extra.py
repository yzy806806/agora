"""Webhook CRUD — list, update, delete, and trigger-history operations.

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


async def list_webhooks(
    db: Any, dialect: Dialect,
    project_id: str | None = None,
    limit: int = 100, offset: int = 0,
) -> list[dict]:
    """List webhooks, optionally filtered by project_id."""
    clauses, params = [], []
    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])
    sql, params = dialect.render(
        f"SELECT * FROM webhooks {where} "
        "ORDER BY created_at DESC LIMIT ? OFFSET ?", params)
    async with db.execute(sql, params) as cur:
        rows = [_normalize_webhook(dict(r)) async for r in cur]
    return rows


async def update_webhook(
    db: Any, dialect: Dialect,
    webhook_id: str, updates: dict,
) -> Optional[dict]:
    """Update selected fields on a webhook. Returns updated row or None."""
    allowed = {
        "name", "description", "secret_hash", "pipeline_template",
        "events", "enabled", "allowed_ips", "max_triggers_per_hour",
    }
    sets, params = [], []
    for k, v in updates.items():
        if k not in allowed:
            continue
        if k in ("pipeline_template", "events", "allowed_ips"):
            v = json.dumps(v)
        elif k == "enabled":
            v = 1 if v else 0
        sets.append(f"{k} = ?")
        params.append(v)
    if not sets:
        from .webhook_crud import get_webhook
        return await get_webhook(db, dialect, webhook_id)
    params.append(webhook_id)
    sql, params = dialect.render(
        f"UPDATE webhooks SET {', '.join(sets)} WHERE id = ?", params)
    await db.execute(sql, params)
    await db.commit()
    from .webhook_crud import get_webhook
    return await get_webhook(db, dialect, webhook_id)


async def delete_webhook(
    db: Any, dialect: Dialect, webhook_id: str,
) -> bool:
    """Delete a webhook. Returns True if a row was deleted."""
    sql, params = dialect.render(
        "DELETE FROM webhooks WHERE id = ?", [webhook_id])
    cur = await db.execute(sql, params)
    await db.commit()
    return cur.rowcount > 0
