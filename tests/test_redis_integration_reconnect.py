"""RedisBus integration: reconnection behavior.

Tests that new RedisBus instances can connect after previous
ones are closed, simulating a reconnection scenario.
Requires Docker.
"""

from __future__ import annotations

import asyncio

import pytest

from agora.coordinator.broadcast_bus_redis import RedisBus


def _make_handler(store: list):
    async def _handler(payload):
        store.append(payload)
    return _handler  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_reconnect_new_bus_after_close(redis_url: str):
    """After closing a bus, a new bus can connect and pub/sub works."""
    # Phase 1: first bus pair works
    pub1 = RedisBus(redis_url)
    sub1 = RedisBus(redis_url)
    await pub1.connect()
    await sub1.connect()
    received: list[dict] = []
    await sub1.subscribe("default", _make_handler(received))
    await asyncio.sleep(0.3)
    await pub1.publish("default", {"phase": "before"})
    await asyncio.sleep(0.5)
    assert len(received) >= 1
    assert received[0]["phase"] == "before"
    await pub1.close()
    await sub1.close()

    # Phase 2: new bus pair connects on same Redis
    pub2 = RedisBus(redis_url)
    sub2 = RedisBus(redis_url)
    await pub2.connect()
    await sub2.connect()
    recv2: list[dict] = []
    await sub2.subscribe("default", _make_handler(recv2))
    await asyncio.sleep(0.3)
    await pub2.publish("default", {"phase": "after"})
    await asyncio.sleep(0.5)
    assert len(recv2) >= 1
    assert recv2[0]["phase"] == "after"
    await pub2.close()
    await sub2.close()


@pytest.mark.asyncio
async def test_close_cancels_listener(redis_url: str):
    """Closing a RedisBus cancels its listener task."""
    pub = RedisBus(redis_url)
    sub = RedisBus(redis_url)
    await pub.connect()
    await sub.connect()
    recv: list[dict] = []
    await sub.subscribe("default", _make_handler(recv))
    await asyncio.sleep(0.2)

    # Listener task should exist
    assert sub._listener_task is not None
    assert not sub._listener_task.done()

    await sub.close()

    # Listener task should be cancelled
    await asyncio.sleep(0.1)
    assert sub._listener_task.cancelled() or sub._listener_task.done()
    await pub.close()
