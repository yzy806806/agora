"""SQL dialect abstraction — public facade.

Re-exports SQLDialect ABC, RenderedSQL, SqliteDialect, PostgresDialect,
and provides backward-compatible ``Dialect`` class + singletons.
"""
from __future__ import annotations

from typing import Any

from .dialect_base import RenderedSQL, SQLDialect
from .dialect_sqlite import SqliteDialect
from .dialect_postgres import PostgresDialect

__all__ = [
    "SQLDialect", "SqliteDialect", "PostgresDialect",
    "RenderedSQL", "Dialect", "SQLITE_DIALECT", "POSTGRES_DIALECT",
]


# --- Backward-compatible Dialect class (Phase A.1) ---


class Dialect:
    """Legacy dialect wrapper (Phase A.1).

    Delegates to the new ABC-based dialects internally.
    Prefer SqliteDialect / PostgresDialect directly.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        if name == "sqlite":
            self._impl: SQLDialect = SqliteDialect()
        elif name == "postgres":
            self._impl = PostgresDialect()
        else:
            raise ValueError(f"Unknown dialect: {name}")

    def render(self, sql: str, params: list[Any] | None = None
               ) -> tuple[str, list[Any]]:
        r = self._impl.render(sql, params)
        return r.sql, r.params

    def last_insert_id_sql(self) -> str:
        if self.name == "postgres":
            return "SELECT lastval()"
        return "SELECT last_insert_rowid()"

    def insert_or_ignore(self) -> str:
        if self.name == "postgres":
            return "INSERT INTO"
        return "INSERT OR IGNORE INTO"

    def insert_or_replace(self) -> str:
        if self.name == "postgres":
            return "INSERT INTO"
        return "INSERT OR REPLACE INTO"


SQLITE_DIALECT = Dialect("sqlite")
POSTGRES_DIALECT = Dialect("postgres")
