"""Pytest fixtures for Postgres integration tests.

Provides a real Postgres container via testcontainers-python.
Each test gets a clean database.
"""

from __future__ import annotations

import os

import pytest

# Skip if env var set
if os.getenv("AGORA_SKIP_POSTGRES_TESTS") == "1":
    collect_ignore_glob = ["test_postgres_integration.py"]


@pytest.fixture(scope="session")
def postgres_container():
    """Start a Postgres container for the test session."""
    from testcontainers.postgres import PostgresContainer

    pg = PostgresContainer(
        "postgres:16-alpine",
        username="agora_test",
        password="agora_test",
        dbname="agora_test",
    )
    pg.start()
    yield pg
    pg.stop()


@pytest.fixture(scope="session")
def postgres_dsn(postgres_container) -> str:
    """Return the DSN for the test Postgres instance."""
    return postgres_container.get_connection_url()


@pytest.fixture(scope="session")
def _pg_backend(postgres_dsn):
    """Create a PostgresBackend (session-scoped pool)."""
    from tests.postgres_backend import PostgresBackend

    backend = PostgresBackend(
        dsn=postgres_dsn,
        pool_min_size=2,
        pool_max_size=5,
    )
    yield backend
    import asyncio
    loop = asyncio.new_event_loop()
    loop.run_until_complete(backend.close())
    loop.close()


@pytest.fixture(autouse=True)
async def clean_db(_pg_backend):
    """Drop and recreate all tables before each test."""
    pool = await _pg_backend._ensure_pool()
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS messages CASCADE")
        await conn.execute("DROP TABLE IF EXISTS votes CASCADE")
        await conn.execute("DROP TABLE IF EXISTS tasks CASCADE")
        await conn.execute("DROP TABLE IF EXISTS notifications CASCADE")
        await conn.execute("DROP TABLE IF EXISTS roles CASCADE")
        await conn.execute("DROP TABLE IF EXISTS motions CASCADE")
        await conn.execute("DROP TABLE IF EXISTS agents CASCADE")
    await _pg_backend.initialize()


@pytest.fixture
def backend(_pg_backend):
    """Provide the PostgresBackend for tests."""
    return _pg_backend
