"""Notification CRUD — backend-agnostic."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect

logger = logging.getLogger(__name__)


async def create_notification(
    db: Any, dialect: Dialect,
    type: str, title: str, body: str,
    project_id: str, priority: str = "medium",
) -> dict:
    nid = uuid.uuid4().hex[:16]
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": nid, "type": type, "title": title, "body": body,
        "project_id": project_id, "priority": priority,
        "created_at": now, "read": 0,
    }
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["?"] * len(row))
    sql, params = dialect.render(
        f"INSERT INTO notifications ({cols}) "
        f"VALUES ({placeholders})", list(row.values()))
    await db.execute(sql, params)
    await db.commit()
    return _row_to_dict(row)


async def get_notification(
    db: Any, dialect: Dialect, notif_id: str,
) -> Optional[dict]:
    sql, params = dialect.render(
        "SELECT * FROM notifications WHERE id = ?", [notif_id])
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return _row_to_dict(dict(row)) if row else None


async def list_notifications(
    db: Any, dialect: Dialect,
    project_id: Optional[str] = None,
    unread_only: bool = False,
    priority: Optional[str] = None,
    limit: int = 50, offset: int = 0,
) -> list[dict]:
    clauses, params = [], []
    if project_id is not None:
        clauses.append("project_id = ?"); params.append(project_id)
    if unread_only:
        clauses.append("read = 0")
    if priority is not None:
        clauses.append("priority = ?"); params.append(priority)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])
    sql, params = dialect.render(
        f"SELECT * FROM notifications {where} "
        "ORDER BY created_at DESC LIMIT ? OFFSET ?", params)
    async with db.execute(sql, params) as cur:
        rows = [row async for row in cur]
    return [_row_to_dict(dict(r)) for r in rows]


async def count_notifications(
    db: Any, dialect: Dialect,
    project_id: Optional[str] = None,
    unread_only: bool = False,
    priority: Optional[str] = None,
) -> tuple[int, int]:
    clauses, params = [], []
    if project_id is not None:
        clauses.append("project_id = ?"); params.append(project_id)
    if priority is not None:
        clauses.append("priority = ?"); params.append(priority)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql, params = dialect.render(
        f"SELECT COUNT(*) FROM notifications {where}", params)
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    total = row[0]
    unread_clauses = clauses + ["read = 0"]
    unread_params = list(params)
    unread_where = f"WHERE {' AND '.join(unread_clauses)}"
    usql, uparams = dialect.render(
        f"SELECT COUNT(*) FROM notifications {unread_where}",
        unread_params)
    async with db.execute(usql, uparams) as cur:
        row = await cur.fetchone()
    return total, row[0]


async def mark_read(
    db: Any, dialect: Dialect, notif_id: str,
) -> Optional[dict]:
    sql, params = dialect.render(
        "UPDATE notifications SET read = 1 WHERE id = ?",
        [notif_id])
    await db.execute(sql, params)
    await db.commit()
    return await get_notification(db, dialect, notif_id)


async def mark_all_read(
    db: Any, dialect: Dialect,
    project_id: Optional[str] = None,
) -> int:
    if project_id is not None:
        sql, params = dialect.render(
            "UPDATE notifications SET read = 1 "
            "WHERE project_id = ?", [project_id])
    else:
        sql, params = dialect.render(
            "UPDATE notifications SET read = 1", [])
    cur = await db.execute(sql, params)
    await db.commit()
    return cur.rowcount


def _row_to_dict(row: dict) -> dict:
    d = dict(row)
    d["read"] = bool(d.get("read", 0))
    return d
