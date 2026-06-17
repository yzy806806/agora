"""Postgres integration test helper.

Manages pool lifecycle within the test's own event loop to avoid
loop-mismatch issues with session-scoped async fixtures.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import asyncpg
import pytest

from tests.postgres_backend import PostgresBackend
from tests.postgres_ddl import POSTGRES_DDL


def _skip_if_disabled():
    if os.getenv("AGORA_SKIP_POSTGRES_TESTS") == "1":
        pytest.skip("AGORA_SKIP_POSTGRES_TESTS=1")


def _docker_available() -> bool:
    try:
        import docker
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


_pg_container = None


async def get_pg_backend() -> PostgresBackend:
    """Create a PostgresBackend with a fresh pool on the current loop.

    Starts a Postgres container if not already running.
    """
    global _pg_container
    if not _docker_available():
        pytest.skip("Docker not available")
    if _pg_container is None:
        from testcontainers.postgres import PostgresContainer
        _pg_container = PostgresContainer(
            "postgres:16-alpine",
            username="agora_test",
            password="agora_test",
            dbname="agora_test",
        )
        _pg_container.start()
    dsn = _pg_container.get_connection_url().replace("+psycopg2", "")
    be = PostgresBackend(dsn=dsn, pool_min_size=2, pool_max_size=5)
    return be


async def reset_schema(backend: PostgresBackend) -> None:
    """Drop all tables and recreate schema."""
    pool = await backend._ensure_pool()
    async with pool.acquire() as conn:
        for table in [
            "messages", "votes", "tasks",
            "notifications", "roles", "motions", "agents",
        ]:
            await conn.execute(
                f"DROP TABLE IF EXISTS {table} CASCADE"
            )
    await backend.initialize()
