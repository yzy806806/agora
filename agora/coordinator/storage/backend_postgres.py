"""Postgres storage backend using asyncpg connection pool.

Implements the StorageBackend ABC from backend.py with asyncpg
Pool, $N placeholders, TIMESTAMPTZ, JSONB, BOOLEAN types.

Composition: mixins first, then StorageBackend in MRO.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import asyncpg

from .backend import StorageBackend
from .backend_postgres_conn import PostgresConnectionOps
from .backend_postgres_queries import PostgresQueryOps
from .dialect import POSTGRES_DIALECT, Dialect

logger = logging.getLogger(__name__)

_DEFAULT_POOL_MIN = 2
_DEFAULT_POOL_MAX = 20
_DEFAULT_ACQUIRE_TIMEOUT = 30


class PostgresBackend(
    PostgresConnectionOps, PostgresQueryOps, StorageBackend,
):
    """Postgres backend backed by asyncpg connection pool.

    MRO: PostgresBackend → PostgresConnectionOps →
         PostgresQueryOps → StorageBackend → ABC
    """

    def __init__(
        self,
        database_url: str,
        pool_min_size: int = _DEFAULT_POOL_MIN,
        pool_max_size: int = _DEFAULT_POOL_MAX,
        pool_acquire_timeout: float = _DEFAULT_ACQUIRE_TIMEOUT,
    ) -> None:
        self._database_url = database_url
        self._pool_min = pool_min_size
        self._pool_max = pool_max_size
        self._acquire_timeout = pool_acquire_timeout
        self._pool: Optional[asyncpg.Pool] = None
        self._dialect = POSTGRES_DIALECT
        self._current_conn: Any = None

    @property
    def dialect(self) -> Dialect:
        return self._dialect

    async def _ensure_pool(self) -> asyncpg.Pool:
        """Lazily create the connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._database_url,
                min_size=self._pool_min,
                max_size=self._pool_max,
            )
            logger.info(
                "Postgres pool created (min=%d, max=%d)",
                self._pool_min, self._pool_max,
            )
        return self._pool
