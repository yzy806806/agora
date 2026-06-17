"""PostgresBackend query methods (mixin split for file size).

These methods match the StorageBackend ABC signatures:
- execute(sql, params) → Any
- execute_many(sql, params_seq) → None
- fetch_one(sql, params) → Optional[dict]
- fetch_all(sql, params) → list[dict]
- fetch_val(sql, params) → Any
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .backend_postgres_helpers import record_to_dict, records_to_dicts

logger = logging.getLogger(__name__)


class PostgresQueryOps:
    """Query operations for PostgresBackend.

    Expects `self.connection()` from the composing class.
    Uses $1, $2, … placeholders per asyncpg convention.
    """

    async def execute(
        self, sql: str, params: list[Any] | None = None,
    ) -> Any:
        """Execute a single SQL statement (no return rows)."""
        async with self.connection() as conn:  # type: ignore[attr-defined]
            return await conn.execute(sql, *(params or []))

    async def execute_many(
        self, sql: str, params_seq: list[list[Any]],
    ) -> None:
        """Execute a SQL statement with multiple parameter sets."""
        async with self.connection() as conn:  # type: ignore[attr-defined]
            await conn.executemany(sql, params_seq)

    async def fetch_one(
        self, sql: str, params: list[Any] | None = None,
    ) -> Optional[dict[str, Any]]:
        """Return one row as dict, or None."""
        async with self.connection() as conn:  # type: ignore[attr-defined]
            row = await conn.fetchrow(sql, *(params or []))
            if row is None:
                return None
            return record_to_dict(row)

    async def fetch_all(
        self, sql: str, params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return all matching rows as list of dicts."""
        async with self.connection() as conn:  # type: ignore[attr-defined]
            rows = await conn.fetch(sql, *(params or []))
            return records_to_dicts(rows)

    async def fetch_val(
        self, sql: str, params: list[Any] | None = None,
    ) -> Any:
        """Return the first column of the first row."""
        async with self.connection() as conn:  # type: ignore[attr-defined]
            return await conn.fetchval(sql, *(params or []))
