"""Tests for update_status MCP tool."""
from __future__ import annotations

import pytest

from agora.coordinator.mcp.tools.agent_tools import update_status


class TestUpdateStatus:
    @pytest.mark.asyncio
    async def test_valid_status_online(self):
        result = await update_status(status="online")
        assert result["status"] == "online"
        assert "updated_at" in result

    @pytest.mark.asyncio
    async def test_valid_status_offline(self):
        result = await update_status(status="offline")
        assert result["status"] == "offline"

    @pytest.mark.asyncio
    async def test_valid_status_busy(self):
        result = await update_status(status="busy", load=0.8)
        assert result["status"] == "busy"

    @pytest.mark.asyncio
    async def test_invalid_status(self):
        result = await update_status(status="flying")
        assert "error" in result
        assert "Invalid status" in result["error"]
