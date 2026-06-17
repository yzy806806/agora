"""PostgreSQL dialect implementation."""
from __future__ import annotations

import re
from typing import Any

from .dialect_base import RenderedSQL, SQLDialect

# Regex: match ? placeholders (not inside string literals).
_QMARK_RE = re.compile(r"\?")


class PostgresDialect(SQLDialect):
    """Postgres dialect: $1/$2/… placeholders, native JSONB."""

    @property
    def placeholder_style(self) -> str:
        return "numeric"

    @property
    def supports_jsonb(self) -> bool:
        return True

    def render(self, sql: str, params: list[Any] | None = None
               ) -> RenderedSQL:
        """Replace each ``?`` with ``$N`` in order."""
        p = list(params or [])
        idx = 0

        def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
            nonlocal idx
            idx += 1
            return f"${idx}"

        rendered = _QMARK_RE.sub(_replace, sql)
        return RenderedSQL(sql=rendered, params=p)

    # JSONB helpers use native Postgres operators.

    def jsonb_contains(self, column: str, value: str) -> str:
        return f"{column} @> {value}"

    def jsonb_field(self, column: str, key: str) -> str:
        return f"{column} -> {key}"

    def jsonb_field_text(self, column: str, key: str) -> str:
        return f"{column} ->> {key}"

    def last_insert_id_sql(self) -> str:
        """Return SQL to fetch the last auto-generated ID."""
        return "SELECT lastval()"

    def insert_or_ignore(self) -> str:
        """Postgres uses ON CONFLICT instead of INSERT OR IGNORE."""
        return "INSERT INTO"

    def insert_or_replace(self) -> str:
        """Postgres uses ON CONFLICT instead of INSERT OR REPLACE."""
        return "INSERT INTO"
