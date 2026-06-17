"""Vote CRUD operations and statistics — backend-agnostic."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect

logger = logging.getLogger(__name__)


async def add_vote(
    db: Any, dialect: Dialect,
    motion_id: str, agent_id: str, vote: str,
    confidence: float = 1.0, reason: Optional[str] = None,
    vote_type: str = "binary", vote_data: Optional[str] = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        """INSERT INTO votes
           (motion_id, agent_id, vote, vote_type, vote_data,
            confidence, reason, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [motion_id, agent_id, vote, vote_type, vote_data,
         confidence, reason, now],
    )
    await db.execute(sql, params)
    await db.commit()
    id_sql, id_params = dialect.render(dialect.last_insert_id_sql())
    async with db.execute(id_sql, id_params) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else 0


async def get_votes(db: Any, dialect: Dialect,
                    motion_id: str) -> list[dict]:
    sql, params = dialect.render(
        "SELECT * FROM votes WHERE motion_id = ? ORDER BY timestamp",
        [motion_id])
    async with db.execute(sql, params) as cursor:
        return [dict(row) async for row in cursor]


async def has_voted(db: Any, dialect: Dialect,
                    motion_id: str, agent_id: str) -> bool:
    sql, params = dialect.render(
        "SELECT 1 FROM votes WHERE motion_id = ? AND agent_id = ?",
        [motion_id, agent_id])
    async with db.execute(sql, params) as cursor:
        return await cursor.fetchone() is not None


async def count_votes(db: Any, dialect: Dialect,
                      motion_id: str) -> dict[str, int]:
    sql, params = dialect.render(
        "SELECT vote, COUNT(*) as count FROM votes "
        "WHERE motion_id = ? GROUP BY vote", [motion_id])
    async with db.execute(sql, params) as cursor:
        rows = await cursor.fetchall()
    return {row[0]: row[1] for row in rows}


async def get_vote_summary(db: Any, dialect: Dialect,
                           motion_id: str) -> dict:
    votes = await get_votes(db, dialect, motion_id)
    summary: dict = {"yes": 0, "no": 0, "abstain": 0, "total": len(votes)}
    for v in votes:
        choice = v["vote"]
        if choice in summary:
            summary[choice] += 1
    return summary


async def get_active_motion_count(db: Any, dialect: Dialect) -> int:
    sql, params = dialect.render(
        "SELECT COUNT(*) FROM motions "
        "WHERE status IN ('draft','discussing','voting')", [])
    async with db.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else 0


async def get_participant_count(db: Any, dialect: Dialect) -> int:
    sql, params = dialect.render(
        "SELECT COUNT(*) FROM agents WHERE is_online = 1", [])
    async with db.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else 0
