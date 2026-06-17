"""SQLDialect ABC + RenderedSQL dataclass.

This is the base module — no implementation classes here.
Concrete dialects live in dialect_sqlite.py and dialect_postgres.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RenderedSQL:
    """Result of dialect.render(): backend-specific SQL + params."""

    sql: str
    params: list[Any]


class SQLDialect(ABC):
    """Abstract base for SQL dialect differences."""

    @property
    @abstractmethod
    def placeholder_style(self) -> str:
        """'qmark' for ?, 'numeric' for $1/$2/…"""

    @property
    @abstractmethod
    def supports_jsonb(self) -> bool:
        """True when the backend has native JSONB operators."""

    @abstractmethod
    def render(self, sql: str, params: list[Any] | None = None
               ) -> RenderedSQL:
        """Convert generic SQL + params to backend-specific form."""

    def jsonb_contains(self, column: str, value: str) -> str:
        """Return SQL for ``column @> value`` (JSONB contains)."""
        return f"{column} @> {value}"

    def jsonb_field(self, column: str, key: str) -> str:
        """Return SQL for ``column->key`` (JSONB field as JSON)."""
        return f"{column} -> {key}"

    def jsonb_field_text(self, column: str, key: str) -> str:
        """Return SQL for ``column->>key`` (JSONB field as text)."""
        return f"{column} ->> {key}"
