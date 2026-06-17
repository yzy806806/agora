"""Postgres integration tests: Connection pool behavior.

Tests that the asyncpg pool works correctly under concurrent access.
"""

from __future__ import annotations

import asyncio
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
async def test_pool_acquire_and_release():
    """Pool acquires and releases connections correctly."""
    backend = await get_pg_backend()
    try:
        pool = await backend._ensure_pool()
        assert pool.get_idle_size() >= 0
        async with pool.acquire() as conn:
            val = await conn.fetchval("SELECT 1")
            assert val == 1
        assert pool.get_idle_size() >= 1
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_queries():
    """Multiple concurrent queries work via the pool."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        await backend.execute(
            """INSERT INTO agents
               (agent_id, name, model, capabilities,
                role, registered_at, is_online)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            ["pool-agent", "PoolBot", "test", [],
             "expert", now, True],
        )

        async def query_agent() -> dict | None:
            return await backend.fetch_one(
                "SELECT * FROM agents WHERE agent_id = $1",
                ["pool-agent"],
            )

        results = await asyncio.gather(
            *[query_agent() for _ in range(10)],
        )
        assert all(r is not None for r in results)
        assert all(r["name"] == "PoolBot" for r in results)
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pool_min_max_size():
    """Pool respects min/max size settings."""
    backend = await get_pg_backend()
    try:
        pool = await backend._ensure_pool()
        assert pool.get_min_size() == 2
        assert pool.get_max_size() == 5
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_connection_context_manager():
    """connection() yields a usable asyncpg connection."""
    backend = await get_pg_backend()
    try:
        async with backend.connection() as conn:
            val = await conn.fetchval("SELECT 42")
            assert val == 42
    finally:
        await backend.close()
