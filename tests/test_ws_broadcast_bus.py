"""Tests for BroadcastBus wiring into ConnectionHub/ConnectionManager."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agora.coordinator.broadcast_bus import LocalBus
from agora.coordinator.ws import ConnectionHub, ConnectionManager


class TestConnectionHubWithBus:
    @pytest.mark.asyncio
    async def test_broadcast_local_with_no_connections(self):
        """broadcast() with no local connections returns 0."""
        bus = LocalBus()
        hub = ConnectionHub(bus=bus)
        count = await hub.broadcast({"type": "test"})
        assert count == 0

    @pytest.mark.asyncio
    async def test_broadcast_local_and_bus_noop(self):
        """LocalBus.publish() is no-op; local delivery via _broadcast_local."""
        bus = LocalBus()
        hub = ConnectionHub(bus=bus)
        ws = AsyncMock()
        hub.active_connections["a1"] = ws
        count = await hub.broadcast({"type": "msg"})
        assert count == 1
        ws.send_json.assert_called_once_with({"type": "msg"})

    @pytest.mark.asyncio
    async def test_broadcast_excludes_sender(self):
        """broadcast(exclude=...) skips local agent without double delivery."""
        bus = LocalBus()
        hub = ConnectionHub(bus=bus)
        ws1, ws2 = AsyncMock(), AsyncMock()
        hub.active_connections["a1"] = ws1
        hub.active_connections["a2"] = ws2
        count = await hub.broadcast({"type": "msg"}, exclude=["a1"])
        assert count == 1
        ws1.send_json.assert_not_called()
        ws2.send_json.assert_called_once_with({"type": "msg"})

    @pytest.mark.asyncio
    async def test_on_remote_broadcast(self):
        hub = ConnectionHub()
        ws = AsyncMock()
        hub.active_connections["a1"] = ws
        await hub._on_remote_broadcast({
            "payload": {"type": "remote_msg"},
            "exclude": [],
        })
        ws.send_json.assert_called_once_with({"type": "remote_msg"})

    @pytest.mark.asyncio
    async def test_on_remote_broadcast_with_exclude(self):
        hub = ConnectionHub()
        ws1, ws2 = AsyncMock(), AsyncMock()
        hub.active_connections["a1"] = ws1
        hub.active_connections["a2"] = ws2
        await hub._on_remote_broadcast({
            "payload": {"type": "remote_msg"},
            "exclude": ["a2"],
        })
        ws1.send_json.assert_called_once()
        ws2.send_json.assert_not_called()


class TestConnectionManagerSetBus:
    def test_set_bus_propagates_to_default_hub(self):
        mgr = ConnectionManager()
        bus = LocalBus()
        mgr.set_bus(bus)
        assert mgr._default_hub._bus is bus
        assert mgr._bus is bus

    @pytest.mark.asyncio
    async def test_on_remote_broadcast_delegates(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        mgr._default_hub.active_connections["a1"] = ws
        await mgr._on_remote_broadcast({
            "payload": {"type": "remote"},
            "exclude": [],
        })
        ws.send_json.assert_called_once_with({"type": "remote"})
