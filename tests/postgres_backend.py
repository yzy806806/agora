"""PostgresBackend implementation for integration tests.

Mirrors the design in DESIGN-phase14plus.md A.5.
Implements the actual StorageBackend ABC from backend.py.
Will later be moved to agora/coordinator/storage/backend_postgres.py.
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncContextManager, Optional

import asyncpg

from agora.coordinator.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


async def _init_jsonb_codecs(conn: asyncpg.Connection) -> None:
    """Register JSONB codec so asyncpg returns Python objects."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


class PostgresBackend(StorageBackend):
    """asyncpg-backed storage backend with connection pool."""

    def __init__(
        self,
        dsn: str,
        pool_min_size: int = 2,
        pool_max_size: int = 10,
    ) -> None:
        self._dsn = dsn
        self._pool_min = pool_min_size
        self._pool_max = pool_max_size
        self._pool: asyncpg.Pool | None = None
        # Transaction state: when active, use this connection
        self._tx_conn: asyncpg.Connection | None = None
        self._tx_cm: Any = None

    @property
    def dialect(self) -> str:
        return "postgres"

    async def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=self._pool_min,
                max_size=self._pool_max,
                init=_init_jsonb_codecs,
            )
        return self._pool

    # --- connection lifecycle -------------------------------------------

    def connection(self) -> AsyncContextManager[Any]:
        return self._connection()

    @asynccontextmanager
    async def _connection(self):
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            yield conn

    async def initialize(self) -> None:
        """Create schema from DDL."""
        from tests.postgres_ddl import POSTGRES_DDL
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(POSTGRES_DDL)
        logger.info("Postgres schema initialized")

    # --- primitive helpers ----------------------------------------------

    async def _get_conn(self) -> asyncpg.Connection:
        """Get a connection: use tx conn if in transaction, else pool."""
        if self._tx_conn is not None:
            return self._tx_conn
        pool = await self._ensure_pool()
        return await pool.acquire()

    async def _release_conn(self, conn: asyncpg.Connection) -> None:
        """Release a connection back to pool (unless it's the tx conn)."""
        if conn is not self._tx_conn and self._pool:
            await self._pool.release(conn)

    async def execute(
        self, sql: str, params: list[Any] | None = None,
    ) -> Any:
        conn = await self._get_conn()
        try:
            return await conn.execute(sql, *(params or []))
        finally:
            await self._release_conn(conn)

    async def execute_many(
        self, sql: str, params_seq: list[list[Any]],
    ) -> None:
        conn = await self._get_conn()
        try:
            await conn.executemany(sql, params_seq)
        finally:
            await self._release_conn(conn)

    async def fetch_one(
        self, sql: str, params: list[Any] | None = None,
    ) -> Optional[dict[str, Any]]:
        conn = await self._get_conn()
        try:
            row = await conn.fetchrow(sql, *(params or []))
            return dict(row) if row else None
        finally:
            await self._release_conn(conn)

    async def fetch_all(
        self, sql: str, params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        conn = await self._get_conn()
        try:
            rows = await conn.fetch(sql, *(params or []))
            return [dict(r) for r in rows]
        finally:
            await self._release_conn(conn)

    async def fetch_val(
        self, sql: str, params: list[Any] | None = None,
    ) -> Any:
        conn = await self._get_conn()
        try:
            return await conn.fetchval(sql, *(params or []))
        finally:
            await self._release_conn(conn)

    # --- transaction helpers -------------------------------------------

    async def begin(self) -> None:
        """Start a transaction on a dedicated connection."""
        pool = await self._ensure_pool()
        self._tx_conn = await pool.acquire()
        self._tx_cm = self._tx_conn.transaction()
        await self._tx_cm.start()

    async def commit(self) -> None:
        """Commit current transaction and release connection."""
        if self._tx_cm:
            await self._tx_cm.commit()
        if self._tx_conn and self._pool:
            await self._pool.release(self._tx_conn)
        self._tx_conn = None
        self._tx_cm = None

    async def rollback(self) -> None:
        """Rollback current transaction and release connection."""
        if self._tx_cm:
            await self._tx_cm.rollback()
        if self._tx_conn and self._pool:
            await self._pool.release(self._tx_conn)
        self._tx_conn = None
        self._tx_cm = None

    # --- advisory lock -------------------------------------------------

    async def acquire_lock(
        self, name: str, timeout: float = 5.0,
    ) -> bool:
        lock_id = int(hashlib.md5(name.encode()).hexdigest()[:16], 16)
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT pg_try_advisory_lock($1)", lock_id,
            )
            return bool(result)

    async def release_lock(self, name: str) -> None:
        lock_id = int(hashlib.md5(name.encode()).hexdigest()[:16], 16)
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "SELECT pg_advisory_unlock($1)", lock_id,
            )

    async def close(self) -> None:
        """Close pool and release resources."""
        if self._pool:
            await self._pool.close()
            self._pool = None
