"""Postgres integration tests: TIMESTAMPTZ handling.

Tests that asyncpg auto-converts Python datetime <-> TIMESTAMPTZ.
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
async def test_timestamp_roundtrip():
    """Python datetime -> TIMESTAMPTZ -> Python datetime roundtrip."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        await backend.execute(
            """INSERT INTO agents
               (agent_id, name, model, capabilities,
                role, registered_at, is_online)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            ["ts-agent", "TsBot", "test", [],
             "expert", now, True],
        )
        row = await backend.fetch_one(
            "SELECT registered_at FROM agents WHERE agent_id = $1",
            ["ts-agent"],
        )
        assert row is not None
        returned = row["registered_at"]
        assert isinstance(returned, datetime)
        assert returned.tzinfo is not None
        delta = abs((returned - now).total_seconds())
        assert delta < 1.0
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_timestamp_comparison():
    """TIMESTAMPTZ columns support SQL comparison operators."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        past = datetime(2020, 1, 1, tzinfo=timezone.utc)
        await backend.execute(
            """INSERT INTO agents
               (agent_id, name, model, capabilities,
                role, registered_at, is_online)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            ["ts-old", "OldBot", "test", [],
             "expert", past, False],
        )
        await backend.execute(
            """INSERT INTO agents
               (agent_id, name, model, capabilities,
                role, registered_at, is_online)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            ["ts-new", "NewBot", "test", [],
             "expert", now, True],
        )
        rows = await backend.fetch_all(
            "SELECT * FROM agents WHERE registered_at > $1",
            [datetime(2025, 1, 1, tzinfo=timezone.utc)],
        )
        assert len(rows) == 1
        assert rows[0]["agent_id"] == "ts-new"
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_null_timestamp():
    """NULL TIMESTAMPTZ is handled correctly."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        await backend.execute(
            """INSERT INTO agents
               (agent_id, name, model, capabilities,
                role, registered_at, is_online, last_seen_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            ["ts-null", "NullBot", "test", [],
             "expert", now, False, None],
        )
        row = await backend.fetch_one(
            "SELECT last_seen_at FROM agents WHERE agent_id = $1",
            ["ts-null"],
        )
        assert row is not None
        assert row["last_seen_at"] is None
    finally:
        await backend.close()
