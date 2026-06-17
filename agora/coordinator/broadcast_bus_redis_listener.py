"""RedisBus listener task with exponential-backoff reconnection."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_BASE_DELAY = 1.0
_MAX_DELAY = 30.0


def _start_listener(pubsub: Any, handler: Any, instance_id: str) -> asyncio.Task:
    """Spawn an asyncio task that reads from pubsub and calls handler."""
    loop = asyncio.get_running_loop()
    return loop.create_task(_listen_loop(pubsub, handler, instance_id))


async def _listen_loop(
    pubsub: Any, handler: Any, instance_id: str,
) -> None:
    """Main listener loop with reconnection on errors."""
    delay = _BASE_DELAY
    while True:
        try:
            async for raw in pubsub.listen():
                if raw["type"] != "message":
                    continue
                await _dispatch(raw, handler, instance_id)
                delay = _BASE_DELAY  # reset on success
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("RedisBus listener error, reconnecting")
            await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_DELAY)


async def _dispatch(
    raw: dict, handler: Any, instance_id: str,
) -> None:
    """Parse a Redis message and call handler if not from self."""
    try:
        envelope = json.loads(raw["data"])
    except (json.JSONDecodeError, TypeError):
        logger.warning("RedisBus: invalid message payload")
        return
    src = envelope.get("source_instance")
    if src == instance_id:
        return  # skip own broadcasts
    payload = envelope.get("payload", {})
    try:
        await handler(payload)
    except Exception:
        logger.exception("RedisBus handler error")
