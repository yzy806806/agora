"""SQLite storage backend using aiosqlite.

Wraps the existing aiosqlite connection pattern into the
StorageBackend ABC interface.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

import aiosqlite

from .backend import StorageBackend
from .dialect import Dialect, SQLITE_DIALECT
from .schema import SCHEMA_SQL, SCHEMA_VERSION

logger = logging.getLogger(__name__)


class SqliteBackend(StorageBackend):
    """SQLite backend backed by aiosqlite."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    @property
    def dialect(self) -> Dialect:
        return SQLITE_DIALECT

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Async database connection with WAL mode."""
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            await conn.close()

    async def initialize(self) -> None:
        """Initialize SQLite schema and run migrations."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA_SQL)
            await db.execute(
                """CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY, applied_at TEXT)"""
            )
            async with db.execute(
                "SELECT MAX(version) FROM schema_version"
            ) as cur:
                row = await cur.fetchone()
            current_ver = row[0] if row and row[0] else SCHEMA_VERSION
            from .backend_sqlite_migrations import run_migrations
            await run_migrations(db, current_ver)
        logger.info("Database initialized at %s", self.db_path)

    async def execute(self, sql: str, params: list[Any] | None = None
                      ) -> Any:
        async with self.connection() as db:
            cursor = await db.execute(sql, params or [])
            await db.commit()
            return cursor.rowcount

    async def execute_many(self, sql: str,
                           params_seq: list[list[Any]]) -> None:
        async with self.connection() as db:
            await db.executemany(sql, params_seq)
            await db.commit()

    async def fetch_one(self, sql: str, params: list[Any] | None = None
                        ) -> Optional[dict[str, Any]]:
        async with self.connection() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, params or [])
            row = await cursor.fetchone()
            if row is None:
                return None
            return dict(row)

    async def fetch_all(self, sql: str, params: list[Any] | None = None
                        ) -> list[dict[str, Any]]:
        async with self.connection() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, params or [])
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def fetch_val(self, sql: str, params: list[Any] | None = None
                        ) -> Any:
        async with self.connection() as db:
            cursor = await db.execute(sql, params or [])
            row = await cursor.fetchone()
            return row[0] if row else None

    async def begin(self) -> None:
        """SQLite autocommit=off handled by connection context."""

    async def commit(self) -> None:
        """Commit is handled per-operation in SQLite backend."""

    async def rollback(self) -> None:
        """No-op for SQLite in current pattern."""

    async def acquire_lock(self, name: str, timeout: float = 5.0) -> bool:
        """SQLite uses file-level locking; always succeeds."""
        return True

    async def release_lock(self, name: str) -> None:
        """No-op for SQLite."""

    async def close(self) -> None:
        """No persistent pool to close for SQLite."""
        pass
