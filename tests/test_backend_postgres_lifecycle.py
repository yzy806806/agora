"""Tests for PostgresBackend advisory lock + initialize (mocked)."""

from __future__ import annotations

import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from agora.coordinator.storage.backend_postgres import PostgresBackend


def _make_backend_with_mock_conn():
    """Create a backend with a mock connection for testing."""
    backend = PostgresBackend("postgresql://u:***@h/d")
    mock_conn = AsyncMock()

    @asynccontextmanager
    async def _mock_connection(self):
        yield mock_conn

    import types
    backend.connection = types.MethodType(_mock_connection, backend)
    return backend, mock_conn


class TestAdvisoryLock:
    @pytest.mark.asyncio
    async def test_acquire_lock_success(self):
        backend, mock_conn = _make_backend_with_mock_conn()
        mock_conn.fetchval.return_value = True
        result = await backend.acquire_lock("test-lock", timeout=5.0)
        assert result is True
        call_args = mock_conn.fetchval.call_args
        assert "pg_try_advisory_lock" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_acquire_lock_failure(self):
        backend, mock_conn = _make_backend_with_mock_conn()
        mock_conn.fetchval.return_value = False
        result = await backend.acquire_lock("test-lock")
        assert result is False

    @pytest.mark.asyncio
    async def test_release_lock(self):
        backend, mock_conn = _make_backend_with_mock_conn()
        await backend.release_lock("test-lock")
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "pg_advisory_unlock" in call_args[0][0]


class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_creates_schema(self):
        backend = PostgresBackend("postgresql://u:***@h/d")
        mock_conn = AsyncMock()
        mock_pool = AsyncMock()

        @asynccontextmanager
        async def _mock_acquire(timeout=None):
            yield mock_conn

        mock_pool.acquire = _mock_acquire
        with patch(
            "agora.coordinator.storage.backend_postgres.asyncpg.create_pool",
            new=AsyncMock(return_value=mock_pool),
        ):
            await backend.initialize()
            # Should have called execute twice (schema + indexes)
            assert mock_conn.execute.call_count == 2
