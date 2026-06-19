"""Tests for timeout_checker.py (Phase 9.3c)."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from agora.coordinator.timeout_checker import heartbeat_timeout_checker


class TestHeartbeatTimeoutChecker:
    @pytest.mark.asyncio
    async def test_marks_stale_agent_offline(self):
        storage = AsyncMock()
        storage.list_stale_agents = AsyncMock(
            return_value=[{"agent_id": "stale1", "last_seen_at": "old"}]
        )
        storage.set_agent_online = AsyncMock()
        task = asyncio.create_task(
            heartbeat_timeout_checker(storage, interval=999)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        storage.set_agent_online.assert_called_once_with("stale1", False)
