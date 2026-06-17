"""PostgresBackend connection + lifecycle methods.

Split from backend_postgres.py to keep each file under 80 lines.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator

import asyncpg

from .schema_postgres import PG_SCHEMA_SQL
from .schema_postgres_indexes import PG_INDEXES_SQL

if TYPE_CHECKING:
    from asyncpg import Connection

logger = logging.getLogger(__name__)


class PostgresConnectionOps:
    """Connection + lifecycle methods for PostgresBackend.

    Requires `self._ensure_pool()`, `self._acquire_timeout`,
    `self._pool`, `self._database_url` from the composing class.
    """

    @asynccontextmanager
    async def connection(self) -> AsyncIterator["Connection"]:
        """Yield a connection from the pool."""
        pool = await self._ensure_pool()  # type: ignore[attr-defined]
        async with pool.acquire(
            timeout=self._acquire_timeout,  # type: ignore[attr-defined]
        ) as conn:
            yield conn

    async def initialize(self) -> None:
        """Create Postgres tables and indexes."""
        pool = await self._ensure_pool()  # type: ignore[attr-defined]
        async with pool.acquire() as conn:
            await conn.execute(PG_SCHEMA_SQL)
            await conn.execute(PG_INDEXES_SQL)
        logger.info("Postgres schema initialized")

    async def begin(self) -> None:
        """Start a transaction on the current connection."""
        conn = self._current_conn  # type: ignore[attr-defined]
        await conn.execute("BEGIN")

    async def commit(self) -> None:
        """Commit the current transaction."""
        conn = self._current_conn  # type: ignore[attr-defined]
        await conn.execute("COMMIT")

    async def rollback(self) -> None:
        """Roll back the current transaction."""
        conn = self._current_conn  # type: ignore[attr-defined]
        await conn.execute("ROLLBACK")

    async def acquire_lock(self, name: str, timeout: float = 5.0) -> bool:
        """Acquire a Postgres advisory lock (pg_advisory_lock)."""
        lock_id = hash(name) & 0x7FFFFFFFFFFFFFFF
        async with self.connection() as conn:  # type: ignore[attr-defined]
            val = await conn.fetchval(
                "SELECT pg_try_advisory_lock($1)", lock_id,
            )
            return bool(val)

    async def release_lock(self, name: str) -> None:
        """Release a previously acquired advisory lock."""
        lock_id = hash(name) & 0x7FFFFFFFFFFFFFFF
        async with self.connection() as conn:  # type: ignore[attr-defined]
            await conn.execute(
                "SELECT pg_advisory_unlock($1)", lock_id,
            )

    async def close(self) -> None:
        """Close the connection pool and release resources."""
        pool = self._pool  # type: ignore[attr-defined]
        if pool is not None:
            await pool.close()
            self._pool = None  # type: ignore[attr-defined]
            logger.info("Postgres pool closed")
