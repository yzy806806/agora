"""Tests for SQL dialect abstraction (Phase 14+ Part A.4)."""
import pytest

from agora.coordinator.storage.dialect_sqlite import SqliteDialect
from agora.coordinator.storage.dialect_postgres import PostgresDialect
from agora.coordinator.storage.dialect_base import RenderedSQL


# --- SqliteDialect ---


class TestSqliteDialect:
    def setup_method(self):
        self.d = SqliteDialect()

    def test_placeholder_style(self):
        assert self.d.placeholder_style == "qmark"

    def test_supports_jsonb_false(self):
        assert self.d.supports_jsonb is False

    def test_render_passthrough(self):
        r = self.d.render("SELECT * FROM agents WHERE agent_id = ?", ["a1"])
        assert r.sql == "SELECT * FROM agents WHERE agent_id = ?"
        assert r.params == ["a1"]

    def test_render_no_params(self):
        r = self.d.render("SELECT 1")
        assert r.sql == "SELECT 1"
        assert r.params == []

    def test_jsonb_contains_fallback(self):
        result = self.d.jsonb_contains("capabilities", "'code-review'")
        assert "json_extract" in result

    def test_jsonb_field_fallback(self):
        result = self.d.jsonb_field("data", "'key'")
        assert "json_extract" in result

    def test_last_insert_id(self):
        assert "last_insert_rowid" in self.d.last_insert_id_sql()

    def test_insert_or_ignore(self):
        assert self.d.insert_or_ignore() == "INSERT OR IGNORE INTO"
