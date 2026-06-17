"""Tests for storage/agent_heartbeat.py (Phase 9.3c)."""
import json
from datetime import datetime, timezone, timedelta

import aiosqlite
import pytest

from agora.coordinator.storage.agent_heartbeat import (
    update_agent_heartbeat,
    update_agent_capabilities,
    update_agent_model,
    list_stale_agents,
)
from agora.coordinator.storage.dialect import Dialect


@pytest.fixture
async def db(tmp_path):
    """Create an in-memory SQLite DB with agents table."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript("""
        CREATE TABLE agents (
            agent_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            model TEXT DEFAULT '',
            capabilities TEXT DEFAULT '[]',
            role TEXT DEFAULT 'expert',
            registered_at TEXT NOT NULL,
            is_online INTEGER DEFAULT 0,
            last_seen_at TEXT,
            load REAL DEFAULT 0.0,
            active_tasks TEXT DEFAULT '[]'
        );
    """)
    yield conn
    await conn.close()


@pytest.fixture
def dialect() -> Dialect:
    return Dialect("sqlite")


async def _insert_agent(db, agent_id, **overrides):
    """Insert a test agent."""
    now = datetime.now(timezone.utc).isoformat()
    vals = {
        "agent_id": agent_id,
        "name": agent_id,
        "model": "test",
        "capabilities": "[]",
        "role": "expert",
        "registered_at": now,
        "is_online": 1,
        "last_seen_at": now,
        "load": 0.0,
        "active_tasks": "[]",
    }
    vals.update(overrides)
    cols = ", ".join(vals.keys())
    placeholders = ", ".join(["?"] * len(vals))
    await db.execute(
        f"INSERT INTO agents ({cols}) VALUES ({placeholders})",
        list(vals.values()),
    )
    await db.commit()


class TestUpdateAgentHeartbeat:
    @pytest.mark.asyncio
    async def test_updates_load_and_tasks(self, db, dialect):
        await _insert_agent(db, "a1")
        await update_agent_heartbeat(db, dialect, "a1", load=0.7,
                                     active_tasks=["t1", "t2"])
        async with db.execute(
            "SELECT load, active_tasks, is_online FROM agents "
            "WHERE agent_id = ?", ["a1"]
        ) as cur:
            row = dict(await cur.fetchone())
        assert row["load"] == 0.7
        assert json.loads(row["active_tasks"]) == ["t1", "t2"]
        assert row["is_online"] == 1


class TestUpdateAgentCapabilities:
    @pytest.mark.asyncio
    async def test_updates_capabilities(self, db, dialect):
        await _insert_agent(db, "a1")
        await update_agent_capabilities(db, dialect, "a1", ["code", "test"])
        async with db.execute(
            "SELECT capabilities FROM agents WHERE agent_id = ?", ["a1"]
        ) as cur:
            row = dict(await cur.fetchone())
        assert json.loads(row["capabilities"]) == ["code", "test"]


class TestUpdateAgentModel:
    @pytest.mark.asyncio
    async def test_updates_model(self, db, dialect):
        await _insert_agent(db, "a1")
        await update_agent_model(db, dialect, "a1", "claude-sonnet-4")
        async with db.execute(
            "SELECT model FROM agents WHERE agent_id = ?", ["a1"]
        ) as cur:
            row = dict(await cur.fetchone())
        assert row["model"] == "claude-sonnet-4"


class TestListStaleAgents:
    @pytest.mark.asyncio
    async def test_finds_stale_agent(self, db, dialect):
        old_time = (
            datetime.now(timezone.utc) - timedelta(seconds=200)
        ).isoformat()
        await _insert_agent(db, "stale", last_seen_at=old_time)
        stale = await list_stale_agents(db, dialect, timeout_seconds=120)
        assert len(stale) == 1
        assert stale[0]["agent_id"] == "stale"

    @pytest.mark.asyncio
    async def test_skips_recent_agent(self, db, dialect):
        await _insert_agent(db, "fresh")
        stale = await list_stale_agents(db, dialect, timeout_seconds=120)
        assert len(stale) == 0

    @pytest.mark.asyncio
    async def test_skips_offline_agent(self, db, dialect):
        old_time = (
            datetime.now(timezone.utc) - timedelta(seconds=200)
        ).isoformat()
        await _insert_agent(db, "offline", last_seen_at=old_time,
                            is_online=0)
        stale = await list_stale_agents(db, dialect, timeout_seconds=120)
        assert len(stale) == 0
