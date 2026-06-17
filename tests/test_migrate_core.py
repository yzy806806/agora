"""Tests for migrate_core: row conversion and SQLite reading."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from agora.coordinator.storage.migrate_core import (
    _convert_row,
    read_sqlite_tables,
)


def _make_sqlite_db(path: str) -> None:
    """Create a minimal SQLite DB for testing."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE agents ("
        "agent_id TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "hermes_endpoint TEXT, model TEXT, capabilities TEXT, "
        "role TEXT DEFAULT 'expert', registered_at TEXT NOT NULL, "
        "is_online INTEGER DEFAULT 0, last_seen_at TEXT, "
        "agent_type TEXT DEFAULT 'hermes', "
        "max_concurrent_tasks INTEGER DEFAULT 2, "
        "agent_token TEXT DEFAULT '', is_approved INTEGER DEFAULT 0, "
        "approval_status TEXT DEFAULT 'pending', "
        "load REAL DEFAULT 0.0, active_tasks TEXT DEFAULT '[]', "
        "tpm_limit INTEGER DEFAULT 10000, "
        "tpm_burst_factor REAL DEFAULT 1.5, "
        "allowed_discussion_roles TEXT DEFAULT '[\"participant\"]')"
    )
    conn.execute(
        "INSERT INTO agents VALUES ("
        "'agent-1', 'TestAgent', 'http://localhost:8080', "
        "'gpt-4', '[\"code-review\"]', 'expert', "
        "'2024-01-15T10:30:00+00:00', 1, "
        "'2024-01-15T11:00:00+00:00', 'hermes', "
        "2, 'tok123', 1, 'approved', "
        "0.5, '[\"task-1\"]', 10000, 1.5, "
        "'[\"participant\"]')"
    )
    conn.commit()
    conn.close()


class TestConvertRow:
    def test_converts_boolean_cols(self) -> None:
        row = {
            "agent_id": "a1",
            "is_online": 1,
            "is_approved": 0,
            "name": "test",
        }
        result = _convert_row("agents", row)
        assert result["is_online"] is True
        assert result["is_approved"] is False

    def test_converts_jsonb_cols(self) -> None:
        row = {
            "agent_id": "a1",
            "capabilities": '["code-review"]',
            "active_tasks": '["t1"]',
            "name": "test",
        }
        result = _convert_row("agents", row)
        assert result["capabilities"] == ["code-review"]
        assert result["active_tasks"] == ["t1"]

    def test_converts_timestamp_cols(self) -> None:
        row = {
            "agent_id": "a1",
            "registered_at": "2024-01-15T10:30:00+00:00",
            "name": "test",
        }
        result = _convert_row("agents", row)
        from datetime import datetime
        assert isinstance(result["registered_at"], datetime)

    def test_passthrough_other_cols(self) -> None:
        row = {"agent_id": "a1", "name": "Test", "load": 0.5}
        result = _convert_row("agents", row)
        assert result["name"] == "Test"
        assert result["load"] == 0.5


class TestReadSqliteTables:
    def test_reads_existing_tables(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_sqlite_db(db_path)
            result = read_sqlite_tables(db_path)
            assert "agents" in result
            assert len(result["agents"]) == 1
            assert result["agents"][0]["agent_id"] == "agent-1"
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_missing_tables_return_empty(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_sqlite_db(db_path)
            result = read_sqlite_tables(db_path)
            # Tables that don't exist should have empty lists
            assert result["motions"] == []
            assert result["tasks"] == []
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_all_postgres_tables_represented(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_sqlite_db(db_path)
            result = read_sqlite_tables(db_path)
            from agora.coordinator.storage.schema_postgres import (
                POSTGRES_TABLES,
            )
            for table in POSTGRES_TABLES:
                assert table in result
        finally:
            Path(db_path).unlink(missing_ok=True)
