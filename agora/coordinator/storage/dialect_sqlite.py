"""SQLite dialect implementation."""
from __future__ import annotations

from typing import Any

from .dialect_base import RenderedSQL, SQLDialect


class SqliteDialect(SQLDialect):
    """SQLite dialect: ? placeholders, no native JSONB."""

    @property
    def placeholder_style(self) -> str:
        return "qmark"

    @property
    def supports_jsonb(self) -> bool:
        return False

    def render(self, sql: str, params: list[Any] | None = None
               ) -> RenderedSQL:
        # SQLite uses ? natively — pass through unchanged.
        return RenderedSQL(sql=sql, params=list(params or []))

    # JSONB helpers fall back to json_extract on SQLite.

    def jsonb_contains(self, column: str, value: str) -> str:
        return f"json_extract({column}, '$') LIKE '%' || {value} || '%'"

    def jsonb_field(self, column: str, key: str) -> str:
        return f"json_extract({column}, {key})"

    def jsonb_field_text(self, column: str, key: str) -> str:
        return f"json_extract({column}, {key})"

    def last_insert_id_sql(self) -> str:
        """Return SQL to fetch the last auto-generated ID."""
        return "SELECT last_insert_rowid()"

    def insert_or_ignore(self) -> str:
        """Return SQLite-specific upsert-no-conflict prefix."""
        return "INSERT OR IGNORE INTO"

    def insert_or_replace(self) -> str:
        """Return SQLite-specific upsert-replace prefix."""
        return "INSERT OR REPLACE INTO"
