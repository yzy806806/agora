"""Tests for PostgresBackend pool + lifecycle (mocked asyncpg)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from agora.coordinator.storage.backend_postgres import PostgresBackend


class TestPoolCreation:
    """Test lazy pool creation."""

    @pytest.mark.asyncio
    async def test_ensure_pool_creates_pool(self):
        backend = PostgresBackend("postgresql://u:***@h/d")
        mock_pool = AsyncMock()
        with patch(
            "agora.coordinator.storage.backend_postgres.asyncpg.create_pool",
            new=AsyncMock(return_value=mock_pool),
        ) as mock_create:
            pool = await backend._ensure_pool()
            assert pool is mock_pool
            mock_create.assert_called_once_with(
                "postgresql://u:***@h/d", min_size=2, max_size=20,
            )

    @pytest.mark.asyncio
    async def test_ensure_pool_reuses_existing(self):
        backend = PostgresBackend("postgresql://u:***@h/d")
        mock_pool = AsyncMock()
        backend._pool = mock_pool
        pool = await backend._ensure_pool()
        assert pool is mock_pool


class TestClose:
    """Test pool close."""

    @pytest.mark.asyncio
    async def test_close_closes_pool(self):
        backend = PostgresBackend("postgresql://u:***@h/d")
        mock_pool = AsyncMock()
        backend._pool = mock_pool
        await backend.close()
        mock_pool.close.assert_called_once()
        assert backend._pool is None

    @pytest.mark.asyncio
    async def test_close_noop_when_no_pool(self):
        backend = PostgresBackend("postgresql://u:***@h/d")
        assert backend._pool is None
        await backend.close()  # should not raise
