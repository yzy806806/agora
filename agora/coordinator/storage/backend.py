"""StorageBackend ABC for the Agora Coordinator database layer.

Defines the abstract interface that all database backends must implement.
Currently: SqliteBackend (aiosqlite). Future: PostgresBackend (asyncpg).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from .dialect import Dialect


class StorageBackend(ABC):
    """Abstract database backend for the Agora Coordinator.

    Each method mirrors the aiosqlite / asyncpg primitive that the
    CRUD modules call.  The ``connection()`` context manager yields a
    backend-specific connection object whose public API matches what
    the existing CRUD helpers already use (``.execute``, ``.commit``,
    ``.execute_fetchall``, async-iterable cursors, etc.).
    """

    @property
    @abstractmethod
    def dialect(self) -> Dialect:
        """Return the Dialect instance for this backend."""

    # --- connection lifecycle -------------------------------------------

    @asynccontextmanager
    @abstractmethod
    async def connection(self) -> AsyncIterator[Any]:
        """Yield a live connection suitable for CRUD operations."""

    @abstractmethod
    async def initialize(self) -> None:
        """Create tables / run migrations (called once at startup)."""

    # --- primitive helpers (optional convenience) ----------------------

    @abstractmethod
    async def execute(self, sql: str, params: list[Any] | None = None) -> Any:
        """Execute a single SQL statement (no return rows)."""

    @abstractmethod
    async def execute_many(
        self, sql: str, params_seq: list[list[Any]],
    ) -> None:
        """Execute a SQL statement with multiple parameter sets."""

    @abstractmethod
    async def fetch_one(
        self, sql: str, params: list[Any] | None = None,
    ) -> Optional[dict[str, Any]]:
        """Return one row as dict, or None."""

    @abstractmethod
    async def fetch_all(
        self, sql: str, params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return all matching rows as list of dicts."""

    @abstractmethod
    async def fetch_val(
        self, sql: str, params: list[Any] | None = None,
    ) -> Any:
        """Return the first column of the first row."""

    # --- transaction helpers -------------------------------------------

    @abstractmethod
    async def begin(self) -> None:
        """Start a transaction."""

    @abstractmethod
    async def commit(self) -> None:
        """Commit the current transaction."""

    @abstractmethod
    async def rollback(self) -> None:
        """Roll back the current transaction."""

    # --- advisory lock -------------------------------------------------

    @abstractmethod
    async def acquire_lock(self, name: str, timeout: float = 5.0) -> bool:
        """Acquire a named advisory lock. Returns True on success."""

    @abstractmethod
    async def release_lock(self, name: str) -> None:
        """Release a previously acquired advisory lock."""
