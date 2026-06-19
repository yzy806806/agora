"""Parity tests: LocalBus and RedisBus behavior consistency.

LocalBus.publish() is a no-op (local delivery is handled by
DashboardHub.broadcast_event), so parity tests focus on RedisBus
delivery and shared lifecycle behavior (subscribe, close).
Requires Docker (for Redis).
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from agora.coordinator.broadcast_bus import LocalBus
from agora.coordinator.broadcast_bus_redis import RedisBus


@pytest_asyncio.fixture
async def local_bus():
    b = LocalBus()
    yield b
    await b.close()


# --- LocalBus.publish() is no-op ----------------------------------------

@pytest.mark.asyncio
async def test_localbus_publish_noop(local_bus):
    """LocalBus.publish() does NOT deliver to subscribers (no-op)."""
    recv: list = []

    async def handler(msg):
        recv.append(msg)

    await local_bus.subscribe("default", handler)
    await local_bus.publish("default", {"type": "ping"})
    assert len(recv) == 0


# --- RedisBus delivers messages -----------------------------------------

@pytest.mark.asyncio
async def test_redisbus_delivers(redis_url: str):
    """RedisBus.publish() delivers to subscribers."""
    pub = RedisBus(redis_url)
    sub = RedisBus(redis_url)
    await pub.connect()
    await sub.connect()

    recv: list = []

    async def handler(payload):
        recv.append(payload)

    await sub.subscribe("default", handler)
    await asyncio.sleep(0.3)

    msg = {"type": "ping", "ts": 123}
    await pub.publish("default", msg)
    await asyncio.sleep(0.5)

    assert len(recv) >= 1

    await pub.close()
    await sub.close()


# --- Parity: close clears state -----------------------------------------

@pytest.mark.asyncio
async def test_parity_close_clears(local_bus):
    """After close(), LocalBus clears subscribers."""
    await local_bus.close()
    assert local_bus._subscribers == {}
