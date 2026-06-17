"""Tests for BroadcastBus ABC and LocalBus."""
from __future__ import annotations

import pytest

from agora.coordinator.broadcast_bus import BroadcastBus, LocalBus


def test_cannot_instantiate_abc():
    with pytest.raises(TypeError):
        BroadcastBus()


@pytest.mark.asyncio
async def test_localbus_publish_is_noop():
    """LocalBus.publish() is a no-op — it should NOT dispatch to handlers."""
    bus = LocalBus()
    received = []

    async def handler(msg):
        received.append(msg)

    await bus.subscribe("default", handler)
    await bus.publish("default", {"type": "test"})
    assert len(received) == 0  # no-op, no delivery


@pytest.mark.asyncio
async def test_localbus_subscribe_stores_handler():
    bus = LocalBus()

    async def handler(msg):
        pass

    await bus.subscribe("default", handler)
    assert handler in bus._subscribers.get("default", set())


@pytest.mark.asyncio
async def test_localbus_unsubscribe():
    bus = LocalBus()

    async def handler(msg):
        pass

    await bus.subscribe("default", handler)
    await bus.unsubscribe("default", handler)
    assert "default" not in bus._subscribers


@pytest.mark.asyncio
async def test_localbus_close_clears():
    bus = LocalBus()

    async def handler(msg):
        pass

    await bus.subscribe("default", handler)
    await bus.close()
    assert len(bus._subscribers) == 0
