"""Message CRUD operations — backend-agnostic."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect

logger = logging.getLogger(__name__)


async def add_message(
    db: Any, dialect: Dialect,
    motion_id: str, agent_id: str, round_num: int,
    stance: str, content: str,
    evidence: list[dict] | None = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    evidence_json = json.dumps(evidence or [])
    sql, params = dialect.render(
        """INSERT INTO messages
           (motion_id, agent_id, round_num, stance, content, evidence, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [motion_id, agent_id, round_num, stance, content,
         evidence_json, now],
    )
    await db.execute(sql, params)
    await db.commit()
    id_sql, id_params = dialect.render(dialect.last_insert_id_sql())
    async with db.execute(id_sql, id_params) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else 0


async def get_messages(
    db: Any, dialect: Dialect,
    motion_id: str, round_num: Optional[int] = None,
    agent_id: Optional[str] = None,
) -> list[dict]:
    query = "SELECT * FROM messages WHERE motion_id = ?"
    params: list = [motion_id]
    if round_num is not None:
        query += " AND round_num = ?"; params.append(round_num)
    if agent_id is not None:
        query += " AND agent_id = ?"; params.append(agent_id)
    query += " ORDER BY timestamp ASC"
    sql, params = dialect.render(query, params)
    async with db.execute(sql, params) as cursor:
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def count_messages_by_round(
    db: Any, dialect: Dialect,
    motion_id: str, round_num: int,
) -> int:
    sql, params = dialect.render(
        "SELECT COUNT(*) FROM messages WHERE motion_id = ? AND round_num = ?",
        [motion_id, round_num])
    async with db.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else 0
