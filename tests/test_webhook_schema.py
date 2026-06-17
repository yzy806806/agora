"""Tests for webhook schema DDL and migration (SQLite + Postgres)."""

import re

import pytest
import pytest_asyncio

from agora.coordinator.storage.schema import (
    MIGRATION_16_TO_17, SCHEMA_SQL, SCHEMA_VERSION,
)
from agora.coordinator.storage.schema_webhooks import (
    WEBHOOKS_BOOLEAN_COLUMNS, WEBHOOKS_JSONB_COLUMNS,
    WEBHOOKS_POSTGRES_DDL, WEBHOOKS_POSTGRES_TABLES,
    WEBHOOKS_SQLITE_DDL, WEBHOOKS_TIMESTAMP_COLUMNS,
)
from agora.coordinator.storage.schema_postgres import (
    BOOLEAN_COLUMNS, JSONB_COLUMNS, PG_SCHEMA_SQL,
    POSTGRES_TABLES, TIMESTAMP_COLUMNS,
)


def test_schema_version_bumped():
    assert SCHEMA_VERSION >= 17


def test_migration_16_to_17_defined():
    assert len(MIGRATION_16_TO_17) == 4  # 2 tables + 2 indexes


def test_sqlite_ddl_in_schema():
    assert "CREATE TABLE IF NOT EXISTS webhooks" in SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS webhook_trigger_history" in SCHEMA_SQL
    assert "idx_webhooks_project" in SCHEMA_SQL
    assert "idx_webhook_history_webhook" in SCHEMA_SQL


def test_postgres_ddl_in_schema():
    assert "CREATE TABLE IF NOT EXISTS webhooks" in PG_SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS webhook_trigger_history" in PG_SCHEMA_SQL
    assert "JSONB" in PG_SCHEMA_SQL.split("webhooks")[1].split(";")[0]
    assert "BIGSERIAL" in PG_SCHEMA_SQL.split("webhook_trigger_history")[1][:80]


def test_postgres_tables_registered():
    assert "webhooks" in POSTGRES_TABLES
    assert "webhook_trigger_history" in POSTGRES_TABLES


def test_postgres_jsonb_columns():
    assert "webhooks" in JSONB_COLUMNS
    assert "pipeline_template" in JSONB_COLUMNS["webhooks"]
    assert "events" in JSONB_COLUMNS["webhooks"]
    assert "allowed_ips" in JSONB_COLUMNS["webhooks"]


def test_postgres_boolean_columns():
    assert "webhooks" in BOOLEAN_COLUMNS
    assert "enabled" in BOOLEAN_COLUMNS["webhooks"]
    assert "webhook_trigger_history" in BOOLEAN_COLUMNS
    assert "success" in BOOLEAN_COLUMNS["webhook_trigger_history"]


def test_postgres_timestamp_columns():
    assert "webhooks" in TIMESTAMP_COLUMNS
    assert "created_at" in TIMESTAMP_COLUMNS["webhooks"]
    assert "webhook_trigger_history" in TIMESTAMP_COLUMNS
    assert "triggered_at" in TIMESTAMP_COLUMNS["webhook_trigger_history"]


def test_schema_webhooks_module_consistency():
    """Verify schema_webhooks.py metadata matches main schema_postgres.py."""
    for tbl in WEBHOOKS_POSTGRES_TABLES:
        assert tbl in POSTGRES_TABLES
    for tbl, cols in WEBHOOKS_JSONB_COLUMNS.items():
        for c in cols:
            assert c in JSONB_COLUMNS.get(tbl, [])
    for tbl, cols in WEBHOOKS_BOOLEAN_COLUMNS.items():
        for c in cols:
            assert c in BOOLEAN_COLUMNS.get(tbl, [])
    for tbl, cols in WEBHOOKS_TIMESTAMP_COLUMNS.items():
        for c in cols:
            assert c in TIMESTAMP_COLUMNS.get(tbl, [])


@pytest_asyncio.fixture
async def webhook_db(tmp_path):
    """Create a fresh SQLite DB with schema applied."""
    import aiosqlite
    from agora.coordinator.storage.schema import SCHEMA_SQL
    db_path = str(tmp_path / "test_webhooks.db")
    db = await aiosqlite.connect(db_path)
    await db.executescript(SCHEMA_SQL)
    await db.commit()
    yield db
    await db.close()


@pytest.mark.asyncio
async def test_webhook_tables_exist(webhook_db):
    """Verify webhooks tables are created in fresh DB."""
    cursor = await webhook_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('webhooks', 'webhook_trigger_history')"
    )
    tables = {row[0] for row in await cursor.fetchall()}
    assert "webhooks" in tables
    assert "webhook_trigger_history" in tables
