"""Postgres integration tests: CRUD operations.

Tests basic INSERT/SELECT/UPDATE/DELETE against real Postgres
via PostgresBackend. JSONB codec auto-serializes Python lists/dicts.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from tests.postgres_test_helper import get_pg_backend, reset_schema

pytestmark = pytest.mark.skipif(
    os.getenv("AGORA_SKIP_POSTGRES_TESTS") == "1",
    reason="AGORA_SKIP_POSTGRES_TESTS=1",
)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_insert_and_fetch_agent():
    """Insert an agent and fetch it back."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        await backend.execute(
            """INSERT INTO agents
               (agent_id, name, model, capabilities, role,
                registered_at, is_online, agent_type)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            ["agent-1", "TestBot", "gpt-4",
             ["code-review", "testing"], "expert",
             now, True, "hermes"],
        )
        row = await backend.fetch_one(
            "SELECT * FROM agents WHERE agent_id = $1", ["agent-1"],
        )
        assert row is not None
        assert row["name"] == "TestBot"
        assert row["capabilities"] == ["code-review", "testing"]
        assert row["is_online"] is True
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_one_returns_none_when_missing():
    """fetch_one returns None for non-existent rows."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        row = await backend.fetch_one(
            "SELECT * FROM agents WHERE agent_id = $1",
            ["no-such-agent"],
        )
        assert row is None
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_all_returns_list():
    """fetch_all returns all matching rows as list of dicts."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        for i in range(3):
            await backend.execute(
                """INSERT INTO agents
                   (agent_id, name, model, capabilities,
                    role, registered_at, is_online)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                [f"agent-{i}", f"Bot-{i}", "test", [],
                 "expert", now, False],
            )
        rows = await backend.fetch_all(
            "SELECT * FROM agents ORDER BY agent_id"
        )
        assert len(rows) == 3
        assert rows[0]["agent_id"] == "agent-0"
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_val_returns_scalar():
    """fetch_val returns the first column of the first row."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        await backend.execute(
            """INSERT INTO agents
               (agent_id, name, model, capabilities,
                role, registered_at, is_online)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            ["agent-cnt", "CountBot", "test", [],
             "expert", now, False],
        )
        count = await backend.fetch_val("SELECT COUNT(*) FROM agents")
        assert count == 1
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_and_verify():
    """Update a row and verify the change."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        await backend.execute(
            """INSERT INTO agents
               (agent_id, name, model, capabilities,
                role, registered_at, is_online)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            ["agent-upd", "OldName", "test", [],
             "expert", now, False],
        )
        await backend.execute(
            "UPDATE agents SET name = $1 WHERE agent_id = $2",
            ["NewName", "agent-upd"],
        )
        row = await backend.fetch_one(
            "SELECT name FROM agents WHERE agent_id = $1",
            ["agent-upd"],
        )
        assert row is not None
        assert row["name"] == "NewName"
    finally:
        await backend.close()
