"""RedisBus integration: multi-subscriber fan-out and serialization.

Requires Docker. Split from test_redis_integration.py to stay <80 lines.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from agora.coordinator.broadcast_bus_redis import RedisBus


@pytest_asyncio.fixture
async def bus_pub_sub(redis_url: str):
    """Publisher + subscriber pair (different instance_ids)."""
    pub = RedisBus(redis_url)
    sub = RedisBus(redis_url)
    await pub.connect()
    await sub.connect()
    yield pub, sub
    await pub.close()
    await sub.close()


def _make_handler(store: list):
    async def _handler(payload):
        store.append(payload)
    return _handler  # type: ignore[return-value]


# --- Test: multi-subscriber fan-out -------------------------------------

@pytest.mark.asyncio
async def test_multi_subscriber_fan_out(redis_url: str):
    """Two subscriber buses both receive a published message."""
    pub = RedisBus(redis_url)
    sub1 = RedisBus(redis_url)
    sub2 = RedisBus(redis_url)
    await pub.connect()
    await sub1.connect()
    await sub2.connect()

    recv1: list[dict] = []
    recv2: list[dict] = []
    await sub1.subscribe("default", _make_handler(recv1))
    await sub2.subscribe("default", _make_handler(recv2))
    await asyncio.sleep(0.3)

    await pub.publish("default", {"type": "fanout"})
    await asyncio.sleep(0.5)

    assert len(recv1) >= 1
    assert recv1[0]["type"] == "fanout"
    assert len(recv2) >= 1
    assert recv2[0]["type"] == "fanout"

    await pub.close()
    await sub1.close()
    await sub2.close()


# --- Test: message serialization round-trip -----------------------------

@pytest.mark.asyncio
async def test_message_serialization(bus_pub_sub):
    """JSON serialization preserves nested structures."""
    pub, sub = bus_pub_sub
    received: list[dict] = []
    await sub.subscribe("t1", _make_handler(received))
    await asyncio.sleep(0.3)

    msg = {"type": "ws_broadcast", "nested": {"a": [1, 2]}, "flag": True}
    await pub.publish("t1", msg)
    await asyncio.sleep(0.5)

    assert len(received) >= 1
    assert received[0] == msg
