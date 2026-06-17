"""Project artifact CRUD — backend-agnostic."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect

logger = logging.getLogger(__name__)


async def put_artifact(
    db: Any, dialect: Dialect,
    project_id: str, key: str,
    value: bytes, content_type: str, created_by: str,
) -> dict:
    """Upsert an artifact. Returns dict representation."""
    now = datetime.now(timezone.utc).isoformat()
    sql1, p1 = dialect.render(
        "SELECT id FROM project_artifacts "
        "WHERE project_id=? AND key=?", [project_id, key])
    async with db.execute(sql1, p1) as cur:
        existing = await cur.fetchone()
    if existing:
        sql2, p2 = dialect.render(
            "UPDATE project_artifacts "
            "SET value=?, content_type=?, updated_at=? "
            "WHERE project_id=? AND key=?",
            [value, content_type, now, project_id, key])
        await db.execute(sql2, p2)
        aid = dict(existing)["id"]
    else:
        aid = f"{project_id}:{key}"
        sql3, p3 = dialect.render(
            "INSERT INTO project_artifacts "
            "(id, project_id, key, value, content_type, "
            "created_by, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [aid, project_id, key, value, content_type,
             created_by, now, now])
        await db.execute(sql3, p3)
    await db.commit()
    return {"id": aid, "project_id": project_id, "key": key,
            "content_type": content_type, "created_by": created_by,
            "created_at": now, "updated_at": now}


async def get_artifact(
    db: Any, dialect: Dialect,
    project_id: str, key: str,
) -> Optional[dict]:
    sql, params = dialect.render(
        "SELECT * FROM project_artifacts "
        "WHERE project_id=? AND key=?", [project_id, key])
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def delete_artifact(
    db: Any, dialect: Dialect,
    project_id: str, key: str,
) -> bool:
    sql, params = dialect.render(
        "DELETE FROM project_artifacts "
        "WHERE project_id=? AND key=?", [project_id, key])
    cursor = await db.execute(sql, params)
    await db.commit()
    return cursor.rowcount > 0


async def list_artifacts(
    db: Any, dialect: Dialect, project_id: str,
) -> list[dict]:
    sql, params = dialect.render(
        "SELECT * FROM project_artifacts "
        "WHERE project_id=?", [project_id])
    async with db.execute(sql, params) as cur:
        return [dict(r) async for r in cur]
