"""Webhook storage — consolidated CRUD + trigger history."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect

logger = logging.getLogger(__name__)


def _normalize(d: dict) -> dict:
    """Normalize webhook dict from DB row."""
    for key in ("pipeline_template", "events", "allowed_ips"):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    if "enabled" in d and isinstance(d["enabled"], int):
        d["enabled"] = bool(d["enabled"])
    return d


async def create_webhook(
    db: Any, dialect: Dialect,
    project_id: str, name: str, secret_hash: str,
    pipeline_template: dict, description: str = "",
    events: list[str] | None = None, enabled: bool = True,
    allowed_ips: list[str] | None = None,
    max_triggers_per_hour: int = 60,
) -> dict:
    """Insert a new webhook and return the row dict."""
    wh_id = uuid.uuid4().hex[:16]
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": wh_id, "project_id": project_id, "name": name,
        "description": description, "secret_hash": secret_hash,
        "pipeline_template": json.dumps(pipeline_template),
        "events": json.dumps(events or ["push"]),
        "enabled": 1 if enabled else 0,
        "allowed_ips": json.dumps(allowed_ips or []),
        "max_triggers_per_hour": max_triggers_per_hour,
        "created_at": now, "last_triggered_at": None,
        "trigger_count": 0, "failure_count": 0,
    }
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["?"] * len(row))
    sql, params = dialect.render(
        f"INSERT INTO webhooks ({cols}) VALUES ({placeholders})",
        list(row.values()),
    )
    await db.execute(sql, params)
    await db.commit()
    row["pipeline_template"] = pipeline_template
    row["events"] = events or ["push"]
    row["enabled"] = enabled
    row["allowed_ips"] = allowed_ips or []
    return row


async def get_webhook(
    db: Any, dialect: Dialect, webhook_id: str,
) -> Optional[dict]:
    """Get a single webhook by ID."""
    sql, params = dialect.render(
        "SELECT * FROM webhooks WHERE id = ?", [webhook_id])
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return _normalize(dict(row)) if row else None


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
        rows = [_normalize(dict(r)) async for r in cur]
    return rows


async def update_webhook(
    db: Any, dialect: Dialect,
    webhook_id: str, updates: dict,
) -> Optional[dict]:
    """Update selected fields on a webhook."""
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
        return await get_webhook(db, dialect, webhook_id)
    params.append(webhook_id)
    sql, params = dialect.render(
        f"UPDATE webhooks SET {', '.join(sets)} WHERE id = ?", params)
    await db.execute(sql, params)
    await db.commit()
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
    webhook_id: str, limit: int = 100, offset: int = 0,
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
