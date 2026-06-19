"""Shared test fixtures for storage layer tests."""
import asyncio
import os
from collections.abc import Generator

import pytest
import pytest_asyncio

from agora.coordinator.storage import Storage


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(loop_scope="session")
async def storage(tmp_path):
    """Create a Storage instance with a temporary database."""
    db_path = str(tmp_path / "test_agora.db")
    s = Storage(db_path)
    await s.init_db()
    yield s


# --- Docker availability check -------------------------------------------

_SKIP_DOCKER = "Docker or testcontainers not available"


def _docker_available() -> bool:
    try:
        import docker  # noqa: F401
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


# --- Redis integration fixture -------------------------------------------

@pytest.fixture(scope="session")
def redis_url() -> Generator[str, None, None]:
    """Provide a real Redis URL via testcontainers (skips if no Docker)."""
    if not _docker_available():
        pytest.skip(_SKIP_DOCKER)
    from testcontainers.redis import RedisContainer

    with RedisContainer() as rc:
        host = rc.get_container_host_ip()
        port = rc.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


# --- Postgres integration helpers ---------------------------------------

_pg_container = None


def _get_postgres_dsn() -> str:
    """Get or create Postgres container, return asyncpg-compatible DSN."""
    global _pg_container
    if not _docker_available():
        pytest.skip(_SKIP_DOCKER)
    if _pg_container is None:
        from testcontainers.postgres import PostgresContainer
        _pg_container = PostgresContainer(
            "postgres:16-alpine",
            username="agora_test",
            password="agora_test",
            dbname="agora_test",
        )
        _pg_container.start()
    dsn = _pg_container.get_connection_url()
    return dsn.replace("+psycopg2", "")
