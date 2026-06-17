"""RedisBus unit tests (mocked redis connections)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agora.coordinator.broadcast_bus_redis import RedisBus, _channel_name

URL = "redis://localhost"


def test_channel_name():
    assert _channel_name("default") == "agora:default:ws"


def _make_bus():
    bus = RedisBus(URL)
    pool = AsyncMock()
    sub = MagicMock()
    sub.aclose = AsyncMock()
    ps = AsyncMock()
    sub.pubsub.return_value = ps
    bus._pub_pool = pool
    bus._sub_conn = sub
    bus._pubsub = ps
    return bus


@pytest.mark.asyncio
async def test_publish_before_connect():
    bus = RedisBus(URL)
    await bus.publish("default", {"type": "msg"})


@pytest.mark.asyncio
async def test_publish_sends_envelope():
    bus = _make_bus()
    await bus.publish("default", {"type": "msg"}, exclude=["a1"])
    call = bus._pub_pool.publish.call_args
    ch = call[0][0]
    data = json.loads(call[0][1])
    assert ch == "agora:default:ws"
    assert data["type"] == "ws_broadcast"
    assert data["payload"] == {"type": "msg"}
    assert "a1" in data["exclude"]


@pytest.mark.asyncio
async def test_subscribe_before_connect_raises():
    bus = RedisBus(URL)
    with pytest.raises(RuntimeError):
        await bus.subscribe("default", AsyncMock())


@pytest.mark.asyncio
async def test_subscribe_calls_pubsub():
    bus = _make_bus()
    handler = AsyncMock()
    await bus.subscribe("default", handler)
    bus._pubsub.subscribe.assert_awaited_once_with("agora:default:ws")
    assert bus._handler is handler


@pytest.mark.asyncio
async def test_unsubscribe_cancels_listener():
    bus = _make_bus()
    mock_task = MagicMock()
    bus._listener_task = mock_task
    bus._subscribed_tenant = "default"
    await bus.unsubscribe("default", AsyncMock())
    mock_task.cancel.assert_called_once()
    bus._pubsub.unsubscribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_cancels_listener():
    bus = _make_bus()
    bus._listener_task = MagicMock()
    await bus.close()
    bus._listener_task.cancel.assert_called_once()
    bus._pub_pool.aclose.assert_awaited_once()

