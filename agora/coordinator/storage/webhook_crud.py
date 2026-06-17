"""Webhook CRUD operations — backend-agnostic.

Functions take a connection object and a Dialect instance,
following the same pattern as other storage sub-modules.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect

logger = logging.getLogger(__name__)


def _normalize_webhook(d: dict) -> dict:
    """Normalize webhook dict from DB row (JSON/bool coercion)."""
    for key in ("pipeline_template", "events", "allowed_ips"):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    if "enabled" in d and isinstance(d["enabled"], int):
        d["enabled"] = bool(d["enabled"])
    return d


async def create_webhook(
    db: Any, dialect: Dialect,
    project_id: str, name: str, secret_hash: str,
    pipeline_template: dict,
    description: str = "",
    events: list[str] | None = None,
    enabled: bool = True,
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
    return _normalize_webhook(dict(row)) if row else None
