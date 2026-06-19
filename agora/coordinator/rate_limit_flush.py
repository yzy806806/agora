"""Phase 9.4: Background task for periodic rate limit DB flush."""

from __future__ import annotations

import asyncio
import logging
import time

import aiosqlite

from .storage import Storage
from .rate_limiter import TokenRateLimiter

logger = logging.getLogger(__name__)

FLUSH_INTERVAL = 60  # seconds
CLEANUP_THRESHOLD = 86400  # keep last 24 hours


async def rate_limit_flush_task(
    token_limiter: TokenRateLimiter, storage: Storage,
) -> None:
    """Background task: flush in-memory buckets to DB every 60s."""
    while True:
        await asyncio.sleep(FLUSH_INTERVAL)
        try:
            await _flush(token_limiter, storage)
        except Exception as exc:
            logger.warning("Rate limit flush failed: %s", exc)


async def _flush(
    token_limiter: TokenRateLimiter, storage: Storage,
) -> None:
    """Single flush cycle."""
    now = time.time()
    window_start = now - (now % 60)
    async with aiosqlite.connect(storage.db_path) as db:
        for agent_id in list(token_limiter._buckets.keys()):
            status = token_limiter.get_status(agent_id)
            await db.execute(
                """INSERT OR REPLACE INTO rate_limit_usage
                   (agent_id, window_start, tokens_consumed,
                    tpm_limit, last_updated)
                   VALUES (?, ?, ?, ?, ?)""",
                (agent_id, window_start,
                 status["tokens_used_this_window"],
                 status["tpm_limit"], now),
            )
        # Cleanup old records (keep last 24h)
        cutoff = now - CLEANUP_THRESHOLD
        await db.execute(
            "DELETE FROM rate_limit_usage WHERE window_start < ?",
            (cutoff,),
        )
        await db.commit()
