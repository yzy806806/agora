"""Postgres integration tests: Transaction handling.

Tests begin/commit/rollback via PostgresBackend.
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
async def test_begin_commit_persists():
    """begin + commit: data is persisted."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        await backend.begin()
        try:
            await backend.execute(
                """INSERT INTO agents
                   (agent_id, name, model, capabilities,
                    role, registered_at, is_online)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                ["tx-agent", "TxBot", "test", [],
                 "expert", now, True],
            )
            await backend.commit()
        except Exception:
            await backend.rollback()
            raise
        row = await backend.fetch_one(
            "SELECT name FROM agents WHERE agent_id = $1",
            ["tx-agent"],
        )
        assert row is not None
        assert row["name"] == "TxBot"
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_begin_rollback_discards():
    """begin + rollback: data is NOT persisted."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        await backend.begin()
        await backend.execute(
            """INSERT INTO agents
               (agent_id, name, model, capabilities,
                role, registered_at, is_online)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            ["rb-agent", "RbBot", "test", [],
             "expert", now, True],
        )
        await backend.rollback()
        row = await backend.fetch_one(
            "SELECT name FROM agents WHERE agent_id = $1",
            ["rb-agent"],
        )
        assert row is None
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rollback_on_exception():
    """Rollback in except block discards partial work."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        try:
            await backend.begin()
            await backend.execute(
                """INSERT INTO agents
                   (agent_id, name, model, capabilities,
                    role, registered_at, is_online)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                ["exc-agent", "ExcBot", "test", [],
                 "expert", now, True],
            )
            raise ValueError("Simulated error")
        except ValueError:
            await backend.rollback()
        row = await backend.fetch_one(
            "SELECT * FROM agents WHERE agent_id = $1",
            ["exc-agent"],
        )
        assert row is None
    finally:
        await backend.close()
