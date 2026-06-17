"""Bootstrap trigger & schedule CRUD — backend-agnostic."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect


async def create_trigger(
    db: Any, dialect: Dialect,
    trigger_type: str, topic: str,
    source: str, context: str, priority: int = 0,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        """INSERT INTO bootstrap_triggers
        (trigger_type, topic, source, context,
         priority, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
        [trigger_type, topic, source, context, priority, now])
    await db.execute(sql, params)
    await db.commit()
    id_sql, id_params = dialect.render(dialect.last_insert_id_sql())
    async with db.execute(id_sql, id_params) as cur:
        row = await cur.fetchone()
    return row[0] if row else 0


async def get_pending_triggers(
    db: Any, dialect: Dialect, limit: int = 10,
) -> list[dict]:
    sql, params = dialect.render(
        """SELECT * FROM bootstrap_triggers
        WHERE status = 'pending'
        ORDER BY priority DESC, created_at ASC LIMIT ?""",
        [limit])
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_trigger_status(
    db: Any, dialect: Dialect,
    trigger_id: int, status: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        "UPDATE bootstrap_triggers "
        "SET status = ?, processed_at = ? WHERE id = ?",
        [status, now, trigger_id])
    await db.execute(sql, params)
    await db.commit()


async def create_schedule(
    db: Any, dialect: Dialect,
    name: str, cron_expression: str,
    topic_template: str, next_run: Optional[str] = None,
) -> int:
    sql, params = dialect.render(
        """INSERT INTO bootstrap_schedules
        (name, cron_expression, topic_template, next_run)
        VALUES (?, ?, ?, ?)""",
        [name, cron_expression, topic_template, next_run])
    await db.execute(sql, params)
    await db.commit()
    id_sql, id_params = dialect.render(dialect.last_insert_id_sql())
    async with db.execute(id_sql, id_params) as cur:
        row = await cur.fetchone()
    return row[0] if row else 0


async def list_schedules(
    db: Any, dialect: Dialect, enabled_only: bool = False,
) -> list[dict]:
    query = "SELECT * FROM bootstrap_schedules"
    params: list = []
    if enabled_only:
        query += " WHERE enabled = 1"
    sql, params = dialect.render(query, params)
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]
