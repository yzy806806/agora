"""Storage queries for metrics history aggregation — backend-agnostic."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .dialect import Dialect

logger = logging.getLogger(__name__)

RANGE_DAYS = {"1h": 1 / 24, "6h": 6 / 24, "1d": 1, "7d": 7, "30d": 30}


async def query_agent_activity(
    db: Any, dialect: Dialect, range_key: str,
    project_id: str | None = None,
) -> dict:
    """Active agents per day from agents + events tables."""
    days = RANGE_DAYS[range_key]
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).strftime("%Y-%m-%dT%H:%M:%S")
    sql, params = dialect.render(
        """SELECT DATE(registered_at) AS day,
        COUNT(*) FILTER (WHERE is_online = 1) AS online,
        COUNT(*) AS total
        FROM agents WHERE registered_at >= ?
        GROUP BY DATE(registered_at) ORDER BY day""",
        [cutoff])
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    labels = [r[0] for r in rows]
    online = [r[1] for r in rows]
    total = [r[2] for r in rows]
    return {
        "labels": labels,
        "datasets": [
            {"label": "Online", "data": online},
            {"label": "Total", "data": total},
        ],
    }


async def query_task_throughput(
    db: Any, dialect: Dialect, range_key: str,
    project_id: str | None = None,
) -> dict:
    """Tasks completed per day from tasks table."""
    days = RANGE_DAYS[range_key]
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).strftime("%Y-%m-%dT%H:%M:%S")
    sql, params = dialect.render(
        """SELECT DATE(completed_at) AS day, COUNT(*) AS cnt
        FROM tasks
        WHERE completed_at >= ? AND status IN ('done','accepted')
        GROUP BY DATE(completed_at) ORDER BY day""",
        [cutoff])
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return {
        "labels": [r[0] for r in rows],
        "datasets": [{"label": "Completed",
                       "data": [r[1] for r in rows]}],
    }
