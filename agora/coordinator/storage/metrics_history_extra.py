"""Discussion outcomes metrics query — backend-agnostic."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .dialect import Dialect

logger = logging.getLogger(__name__)

RANGE_DAYS = {"1h": 1 / 24, "6h": 6 / 24, "1d": 1, "7d": 7, "30d": 30}


async def query_discussion_outcomes(
    db: Any, dialect: Dialect, range_key: str,
    project_id: str | None = None,
) -> dict:
    """Motion outcomes (consensus/deadlock/timeout) from motions."""
    days = RANGE_DAYS[range_key]
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).strftime("%Y-%m-%dT%H:%M:%S")
    sql, params = dialect.render(
        """SELECT COALESCE(decision, 'no_consensus') AS outcome,
        COUNT(*) AS cnt
        FROM motions WHERE closed_at >= ?
        GROUP BY outcome ORDER BY outcome""",
        [cutoff])
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    labels = [r[0] for r in rows]
    data = [r[1] for r in rows]
    return {"labels": labels, "datasets": [{"label": "Count", "data": data}]}
