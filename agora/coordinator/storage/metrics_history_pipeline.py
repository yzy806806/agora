"""Pipeline and rate-limit metrics queries — backend-agnostic."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .dialect import Dialect

logger = logging.getLogger(__name__)

RANGE_DAYS = {"1h": 1 / 24, "6h": 6 / 24, "1d": 1, "7d": 7, "30d": 30}


async def query_pipeline_success_rate(
    db: Any, dialect: Dialect, range_key: str,
    project_id: str | None = None,
) -> dict:
    """Pipeline success vs failure counts from pipeline_runs."""
    days = RANGE_DAYS[range_key]
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).strftime("%Y-%m-%dT%H:%M:%S")
    sql, params = dialect.render(
        """SELECT
        CASE WHEN phase = 'completed' THEN 'success'
             ELSE 'failed' END AS outcome,
        COUNT(*) AS cnt
        FROM pipeline_runs WHERE started_at >= ?
        GROUP BY outcome ORDER BY outcome""",
        [cutoff])
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    labels = [r[0] for r in rows]
    data = [r[1] for r in rows]
    return {"labels": labels, "datasets": [{"label": "Count", "data": data}]}


async def query_rate_limit_usage(
    db: Any, dialect: Dialect, range_key: str,
    project_id: str | None = None,
) -> dict:
    """TPM usage per agent from rate_limit_usage table."""
    days = RANGE_DAYS[range_key]
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).strftime("%Y-%m-%dT%H:%M:%S")
    sql, params = dialect.render(
        """SELECT agent_id,
        SUM(tokens_consumed) AS total_tokens,
        MAX(tpm_limit) AS tpm_limit
        FROM rate_limit_usage WHERE last_updated >= ?
        GROUP BY agent_id ORDER BY total_tokens DESC""",
        [cutoff])
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    labels = [r[0] for r in rows]
    used = [r[1] for r in rows]
    limits = [r[2] for r in rows]
    return {
        "labels": labels,
        "datasets": [
            {"label": "Tokens Used", "data": used},
            {"label": "TPM Limit", "data": limits},
        ],
    }
