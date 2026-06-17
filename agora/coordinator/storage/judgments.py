"""Judgment record CRUD operations — backend-agnostic."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect

logger = logging.getLogger(__name__)


async def record_judgment(
    db: Any, dialect: Dialect,
    motion_id: str, agent_id: str,
    predicted: str, actual: str, confidence: float,
) -> int:
    """Insert a judgment record. Returns the auto-generated id."""
    is_correct = 1 if predicted == actual else 0
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        """INSERT INTO judgment_records
        (motion_id, agent_id, predicted, actual,
         confidence, is_correct, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [motion_id, agent_id, predicted, actual,
         confidence, is_correct, now],
    )
    await db.execute(sql, params)
    await db.commit()
    id_sql, id_params = dialect.render(dialect.last_insert_id_sql())
    async with db.execute(id_sql, id_params) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else 0


async def get_agent_stats(
    db: Any, dialect: Dialect, agent_id: str,
) -> Optional[dict]:
    """Get aggregate stats for an agent."""
    sql, params = dialect.render(
        """SELECT COUNT(*) as total,
        SUM(is_correct) as correct,
        AVG(confidence) as avg_conf
        FROM judgment_records WHERE agent_id = ?""",
        [agent_id])
    async with db.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    if row is None or row["total"] == 0:
        return None
    return dict(row)


async def get_recent_trend(
    db: Any, dialect: Dialect,
    agent_id: str, limit: int = 5,
) -> list[int]:
    """Get the most recent is_correct values for an agent."""
    sql, params = dialect.render(
        """SELECT is_correct FROM judgment_records
        WHERE agent_id = ?
        ORDER BY recorded_at DESC LIMIT ?""",
        [agent_id, limit])
    async with db.execute(sql, params) as cursor:
        rows = await cursor.fetchall()
    return [r["is_correct"] for r in rows]


async def get_leaderboard(
    db: Any, dialect: Dialect, limit: int = 10,
) -> list[dict]:
    """Get agents ranked by correct predictions."""
    sql, params = dialect.render(
        """SELECT agent_id,
        COUNT(*) as total,
        SUM(is_correct) as correct
        FROM judgment_records
        GROUP BY agent_id
        ORDER BY correct DESC, total DESC
        LIMIT ?""",
        [limit])
    async with db.execute(sql, params) as cursor:
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]
