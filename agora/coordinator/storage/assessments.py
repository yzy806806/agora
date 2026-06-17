"""Assessment CRUD operations — backend-agnostic."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect

logger = logging.getLogger(__name__)


async def save_assessment(
    db: Any, dialect: Dialect,
    motion_id: str, round_num: int, result: str,
    consensus_level: str, metrics: dict, rationale: str,
) -> int:
    """Save an assessment record. Returns the auto-generated id."""
    now = datetime.now(timezone.utc).isoformat()
    metrics_json = json.dumps(metrics)
    sql, params = dialect.render(
        """INSERT INTO assessments
           (motion_id, round, result, consensus_level, metrics,
            rationale, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [motion_id, round_num, result, consensus_level,
         metrics_json, rationale, now],
    )
    await db.execute(sql, params)
    await db.commit()
    id_sql, id_params = dialect.render(dialect.last_insert_id_sql())
    async with db.execute(id_sql, id_params) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else 0


async def get_latest_assessment(
    db: Any, dialect: Dialect, motion_id: str,
) -> Optional[dict]:
    """Get the most recent assessment for a motion."""
    sql, params = dialect.render(
        """SELECT * FROM assessments
        WHERE motion_id = ?
        ORDER BY created_at DESC LIMIT 1""",
        [motion_id])
    async with db.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    data = dict(row)
    if data.get("metrics"):
        try:
            data["metrics"] = json.loads(data["metrics"])
        except (json.JSONDecodeError, TypeError):
            pass
    return data


async def get_assessments(
    db: Any, dialect: Dialect, motion_id: str,
) -> list[dict]:
    """Get all assessments for a motion, ordered by time."""
    sql, params = dialect.render(
        """SELECT * FROM assessments
        WHERE motion_id = ?
        ORDER BY created_at""",
        [motion_id])
    async with db.execute(sql, params) as cursor:
        results = []
        async for row in cursor:
            data = dict(row)
            if data.get("metrics"):
                try:
                    data["metrics"] = json.loads(data["metrics"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(data)
        return results
