"""Tests for PostgresBackend query methods (mocked asyncpg)."""

from __future__ import annotations

import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

from agora.coordinator.storage.backend_postgres import PostgresBackend


def _make_backend_with_mock_conn():
    """Create a PostgresBackend with a mocked connection.

    Patches backend.connection() to yield mock_conn.
    """
    backend = PostgresBackend("postgresql://u:***@h/d")
    mock_conn = AsyncMock()

    @asynccontextmanager
    async def _mock_connection(self):
        yield mock_conn

    # Monkey-patch the connection method on the instance
    import types
    backend.connection = types.MethodType(_mock_connection, backend)
    return backend, mock_conn


class TestExecute:
    @pytest.mark.asyncio
    async def test_execute_returns_status(self):
        backend, mock_conn = _make_backend_with_mock_conn()
        mock_conn.execute.return_value = "INSERT 0 1"
        result = await backend.execute(
            "INSERT INTO agents (agent_id, name) VALUES ($1, $2)",
            ["agent-1", "Test"],
        )
        mock_conn.execute.assert_called_once()
        assert result == "INSERT 0 1"

    @pytest.mark.asyncio
    async def test_execute_no_params(self):
        backend, mock_conn = _make_backend_with_mock_conn()
        mock_conn.execute.return_value = "DELETE 5"
        result = await backend.execute("DELETE FROM events")
        mock_conn.execute.assert_called_once_with("DELETE FROM events")


class TestFetchOne:
    @pytest.mark.asyncio
    async def test_fetch_one_returns_dict(self):
        backend, mock_conn = _make_backend_with_mock_conn()
        mock_conn.fetchrow.return_value = {"agent_id": "a1", "name": "X"}
        result = await backend.fetch_one(
            "SELECT agent_id, name FROM agents WHERE agent_id = $1",
            ["a1"],
        )
        assert result == {"agent_id": "a1", "name": "X"}

    @pytest.mark.asyncio
    async def test_fetch_one_returns_none(self):
        backend, mock_conn = _make_backend_with_mock_conn()
        mock_conn.fetchrow.return_value = None
        result = await backend.fetch_one(
            "SELECT * FROM agents WHERE agent_id = $1", ["missing"],
        )
        assert result is None


class TestFetchAll:
    @pytest.mark.asyncio
    async def test_fetch_all_returns_list(self):
        backend, mock_conn = _make_backend_with_mock_conn()
        mock_conn.fetch.return_value = [
            {"id": 1}, {"id": 2},
        ]
        result = await backend.fetch_all("SELECT id FROM events")
        assert len(result) == 2


class TestFetchVal:
    @pytest.mark.asyncio
    async def test_fetch_val_returns_scalar(self):
        backend, mock_conn = _make_backend_with_mock_conn()
        mock_conn.fetchval.return_value = 42
        result = await backend.fetch_val("SELECT COUNT(*) FROM agents")
        assert result == 42


class TestExecuteMany:
    @pytest.mark.asyncio
    async def test_execute_many(self):
        backend, mock_conn = _make_backend_with_mock_conn()
        mock_conn.executemany.return_value = None
        await backend.execute_many(
            "INSERT INTO events (type) VALUES ($1)",
            [["type_a"], ["type_b"]],
        )
        mock_conn.executemany.assert_called_once()
