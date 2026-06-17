"""Tests for webhook CRUD storage (storage/webhook_crud.py + _extra.py)."""
import pytest
import pytest_asyncio
import aiosqlite

from agora.coordinator.storage.webhook_crud import (
    create_webhook, get_webhook,
)
from agora.coordinator.storage.webhook_crud_extra import (
    list_webhooks, update_webhook, delete_webhook,
)
from agora.coordinator.storage.dialect import Dialect


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "webhooks.db")
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("""CREATE TABLE IF NOT EXISTS webhooks (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        secret_hash TEXT NOT NULL,
        pipeline_template TEXT NOT NULL,
        events TEXT NOT NULL DEFAULT '["push"]',
        enabled INTEGER NOT NULL DEFAULT 1,
        allowed_ips TEXT NOT NULL DEFAULT '[]',
        max_triggers_per_hour INTEGER NOT NULL DEFAULT 60,
        created_at TEXT NOT NULL,
        last_triggered_at TEXT,
        trigger_count INTEGER NOT NULL DEFAULT 0,
        failure_count INTEGER NOT NULL DEFAULT 0
    )""")
    await conn.commit()
    yield conn
    await conn.close()


@pytest.fixture
def dialect() -> Dialect:
    return Dialect("sqlite")


TEMPLATE = {"idea": "webhook-triggered", "project_id": "p1"}


@pytest.mark.asyncio
async def test_create_and_get(db, dialect):
    row = await create_webhook(
        db, dialect, project_id="p1", name="ci-hook",
        secret_hash="abc123", pipeline_template=TEMPLATE)
    assert row["project_id"] == "p1"
    assert row["name"] == "ci-hook"
    assert row["enabled"] is True
    fetched = await get_webhook(db, dialect, row["id"])
    assert fetched is not None
    assert fetched["id"] == row["id"]


@pytest.mark.asyncio
async def test_get_not_found(db, dialect):
    assert await get_webhook(db, dialect, "nonexistent") is None


@pytest.mark.asyncio
async def test_list_webhooks(db, dialect):
    await create_webhook(db, dialect, "p1", "h1", "s", TEMPLATE)
    await create_webhook(db, dialect, "p1", "h2", "s", TEMPLATE)
    await create_webhook(db, dialect, "p2", "h3", "s", TEMPLATE)
    all_wh = await list_webhooks(db, dialect)
    assert len(all_wh) == 3
    p1_wh = await list_webhooks(db, dialect, project_id="p1")
    assert len(p1_wh) == 2


@pytest.mark.asyncio
async def test_update_webhook(db, dialect):
    row = await create_webhook(
        db, dialect, "p1", "h1", "s", TEMPLATE)
    updated = await update_webhook(db, dialect, row["id"],
                                   {"name": "renamed", "enabled": False})
    assert updated is not None
    assert updated["name"] == "renamed"
    assert updated["enabled"] is False


@pytest.mark.asyncio
async def test_delete_webhook(db, dialect):
    row = await create_webhook(
        db, dialect, "p1", "h1", "s", TEMPLATE)
    assert await delete_webhook(db, dialect, row["id"]) is True
    assert await get_webhook(db, dialect, row["id"]) is None
    assert await delete_webhook(db, dialect, row["id"]) is False
