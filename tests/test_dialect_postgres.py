"""Tests for PostgresDialect render() method."""

from __future__ import annotations

from agora.coordinator.storage.dialect import (
    Dialect, POSTGRES_DIALECT, SQLITE_DIALECT,
)
from agora.coordinator.storage.dialect_postgres import PostgresDialect
from agora.coordinator.storage.dialect_sqlite import SqliteDialect


class TestPostgresDialectRender:
    def test_qmark_to_numeric(self):
        d = PostgresDialect()
        result = d.render(
            "SELECT * FROM agents WHERE agent_id = ? AND name = ?",
            ["a1", "Test"],
        )
        assert result.sql == (
            "SELECT * FROM agents WHERE agent_id = $1 AND name = $2"
        )
        assert result.params == ["a1", "Test"]

    def test_no_placeholders(self):
        d = PostgresDialect()
        result = d.render("SELECT 1")
        assert result.sql == "SELECT 1"
        assert result.params == []

    def test_single_placeholder(self):
        d = PostgresDialect()
        result = d.render("SELECT * FROM agents WHERE agent_id = ?", ["x"])
        assert result.sql == "SELECT * FROM agents WHERE agent_id = $1"

    def test_placeholder_style(self):
        d = PostgresDialect()
        assert d.placeholder_style == "numeric"

    def test_supports_jsonb(self):
        d = PostgresDialect()
        assert d.supports_jsonb is True


class TestDialectSingletons:
    def test_postgres_dialect_name(self):
        assert POSTGRES_DIALECT.name == "postgres"

    def test_sqlite_dialect_name(self):
        assert SQLITE_DIALECT.name == "sqlite"

    def test_last_insert_id_postgres(self):
        assert POSTGRES_DIALECT.last_insert_id_sql() == "SELECT lastval()"

    def test_last_insert_id_sqlite(self):
        assert "last_insert_rowid" in SQLITE_DIALECT.last_insert_id_sql()
