"""Integration tests for RedisBus against a real Redis instance.

Requires Docker. Uses testcontainers to spin up Redis.
Run: pytest tests/test_redis_integration.py
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from agora.coordinator.broadcast_bus_redis import RedisBus


# --- Fixtures -----------------------------------------------------------

@pytest_asyncio.fixture
async def redis_bus_pair(redis_url: str):
    """Create two connected RedisBus instances (publisher + subscriber).

    RedisBus skips own messages (source_instance check), so we need
    two separate instances to test pub/sub end-to-end.
    """
    pub = RedisBus(redis_url)
    sub = RedisBus(redis_url)
    await pub.connect()
    await sub.connect()
    yield pub, sub
    await pub.close()
    await sub.close()


def _make_handler(store: list):
    """Handler matching RedisBus _dispatch(payload) call."""
    async def _handler(payload):
        store.append(payload)
    return _handler  # type: ignore[return-value]


# --- Test: publish / subscribe end-to-end -------------------------------

@pytest.mark.asyncio
async def test_pubsub_e2e(redis_bus_pair):
    """Publish from one bus, receive on another."""
    pub, sub = redis_bus_pair
    received: list[dict] = []
    await sub.subscribe("default", _make_handler(received))
    await asyncio.sleep(0.3)

    await pub.publish("default", {"type": "hello", "v": 42})
    await asyncio.sleep(0.5)

    assert len(received) >= 1
    assert received[0]["type"] == "hello"
    assert received[0]["v"] == 42
