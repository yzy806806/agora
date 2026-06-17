"""RedisBus — Redis Pub/Sub-backed broadcast for multi-instance Coordinator.

Uses redis.asyncio (redis>=5.0). Channel naming: agora:{tenant}:ws
Message format: JSON with {type, tenant, payload, exclude, source_instance}
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from .broadcast_bus import BroadcastBus, BroadcastHandler
from .broadcast_bus_redis_listener import _start_listener

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "agora"
_RECONNECT_BASE_DELAY = 1.0
_RECONNECT_MAX_DELAY = 30.0


def _channel_name(tenant: str) -> str:
    return f"{_CHANNEL_PREFIX}:{tenant}:ws"


class RedisBus(BroadcastBus):
    """Redis Pub/Sub broadcast bus for cross-instance coordination."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._instance_id = uuid.uuid4().hex[:8]
        self._pub_pool: Any = None
        self._sub_conn: Any = None
        self._pubsub: Any = None
        self._handler: BroadcastHandler | None = None
        self._listener_task: Any = None
        self._subscribed_tenant: str | None = None

    async def connect(self) -> None:
        """Open Redis connections. Call before publish/subscribe."""
        import redis.asyncio as aioredis

        self._pub_pool = aioredis.from_url(
            self._redis_url, decode_responses=True,
        )
        self._sub_conn = aioredis.from_url(
            self._redis_url, decode_responses=True,
        )
        logger.info("RedisBus connected: instance=%s", self._instance_id)

    async def publish(
        self, tenant: str, message: dict[str, Any],
        exclude: list[str] | None = None,
    ) -> None:
        if self._pub_pool is None:
            logger.warning("RedisBus.publish before connect, skipping")
            return
        envelope = {
            "type": "ws_broadcast",
            "tenant": tenant,
            "payload": message,
            "exclude": exclude or [],
            "source_instance": self._instance_id,
        }
        ch = _channel_name(tenant)
        await self._pub_pool.publish(ch, json.dumps(envelope))
        logger.debug("RedisBus publish: channel=%s", ch)

    async def subscribe(
        self, tenant: str, handler: BroadcastHandler,
    ) -> None:
        if self._sub_conn is None:
            raise RuntimeError("RedisBus.subscribe before connect()")
        self._handler = handler
        self._subscribed_tenant = tenant
        self._pubsub = self._sub_conn.pubsub()
        ch = _channel_name(tenant)
        await self._pubsub.subscribe(ch)
        self._listener_task = _start_listener(
            self._pubsub, handler, self._instance_id,
        )
        logger.info("RedisBus subscribed: channel=%s", ch)

    async def unsubscribe(
        self, tenant: str, handler: BroadcastHandler,
    ) -> None:
        """Unsubscribe — cancels listener for the given tenant."""
        if self._listener_task and self._subscribed_tenant == tenant:
            self._listener_task.cancel()
            self._listener_task = None
            self._subscribed_tenant = None
        if self._pubsub:
            await self._pubsub.unsubscribe(_channel_name(tenant))

    async def close(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.aclose()
        if self._sub_conn:
            await self._sub_conn.aclose()
        if self._pub_pool:
            await self._pub_pool.aclose()
        logger.info("RedisBus closed: instance=%s", self._instance_id)
