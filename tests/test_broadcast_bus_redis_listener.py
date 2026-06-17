"""Tests for RedisBus listener dispatch logic."""
from __future__ import annotations

import json

import pytest

from agora.coordinator.broadcast_bus_redis_listener import _dispatch


@pytest.mark.asyncio
async def test_dispatch_calls_handler():
    called = []

    async def handler(msg):
        called.append(msg)

    raw = {"type": "message", "data": json.dumps({
        "type": "ws_broadcast",
        "payload": {"event": "new_message"},
        "source_instance": "other",
    })}
    await _dispatch(raw, handler, "self-inst")
    assert called == [{"event": "new_message"}]


@pytest.mark.asyncio
async def test_dispatch_skips_own_instance():
    called = []

    async def handler(msg):
        called.append(msg)

    raw = {"type": "message", "data": json.dumps({
        "type": "ws_broadcast",
        "payload": {"event": "echo"},
        "source_instance": "self-inst",
    })}
    await _dispatch(raw, handler, "self-inst")
    assert called == []


@pytest.mark.asyncio
async def test_dispatch_invalid_json():
    called = []

    async def handler(msg):
        called.append(msg)

    raw = {"type": "message", "data": "not-json"}
    await _dispatch(raw, handler, "inst-1")
    assert called == []


@pytest.mark.asyncio
async def test_dispatch_handler_error_does_not_raise():
    async def bad_handler(msg):
        raise ValueError("boom")

    raw = {"type": "message", "data": json.dumps({
        "type": "ws_broadcast",
        "payload": {"event": "test"},
        "source_instance": "other",
    })}
    # Should not raise
    await _dispatch(raw, bad_handler, "self-inst")
