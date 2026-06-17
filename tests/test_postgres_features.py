"""Postgres integration tests: advisory lock, execute_many, dialect, booleans.

Tests Postgres-specific features not covered by other test modules.
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
async def test_advisory_lock_acquire_release():
    """Advisory lock can be acquired and released."""
    backend = await get_pg_backend()
    try:
        acquired = await backend.acquire_lock("test-lock-1", timeout=1.0)
        assert acquired is True
        await backend.release_lock("test-lock-1")
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_execute_many():
    """execute_many inserts multiple rows in one call."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        params = [
            ["n-1", "info", "Title 1", "Body 1", "proj", "medium", now],
            ["n-2", "warn", "Title 2", "Body 2", "proj", "high", now],
            ["n-3", "error", "Title 3", "Body 3", "proj", "low", now],
        ]
        await backend.execute_many(
            """INSERT INTO notifications
               (id, type, title, body, project_id, priority, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            params,
        )
        count = await backend.fetch_val(
            "SELECT COUNT(*) FROM notifications"
        )
        assert count == 3
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dialect_property():
    """PostgresBackend.dialect returns 'postgres'."""
    backend = await get_pg_backend()
    try:
        assert backend.dialect == "postgres"
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_boolean_columns():
    """Postgres BOOLEAN columns work correctly (not INTEGER 0/1)."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        await backend.execute(
            """INSERT INTO agents
               (agent_id, name, model, capabilities,
                role, registered_at, is_online, is_approved)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            ["bool-agent", "BoolBot", "test", [],
             "expert", now, True, False],
        )
        row = await backend.fetch_one(
            "SELECT is_online, is_approved FROM agents WHERE agent_id = $1",
            ["bool-agent"],
        )
        assert row is not None
        assert row["is_online"] is True
        assert row["is_approved"] is False
    finally:
        await backend.close()
