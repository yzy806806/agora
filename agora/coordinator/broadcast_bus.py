"""BroadcastBus abstraction for cross-instance WS message delivery.

Phase 14+.B: Decouples broadcast from in-process ConnectionHub so that
future multi-instance deployments can use Redis Pub/Sub while single-instance
deployments keep the current in-memory behavior via LocalBus.

Channel naming convention:
  - ``agora:{tenant}:ws`` — fan-out to all connected agents in a tenant
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# Type alias for broadcast message handlers.
# Handler receives (message: dict) — the payload from a remote broadcast.
BroadcastHandler = Callable[[dict[str, Any]], Awaitable[None]]


class BroadcastBus(ABC):
    """Abstract pub/sub bus for WS broadcast decoupling."""

    @abstractmethod
    async def publish(
        self, tenant: str, message: dict[str, Any],
        exclude: list[str] | None = None,
    ) -> None:
        """Publish *message* to all instances for *tenant*.

        *exclude* lists agent_ids that should not receive the message
        (e.g., the sender).
        """

    @abstractmethod
    async def subscribe(
        self, tenant: str, handler: BroadcastHandler,
    ) -> None:
        """Register *handler* for broadcasts on *tenant*."""

    @abstractmethod
    async def unsubscribe(
        self, tenant: str, handler: BroadcastHandler,
    ) -> None:
        """Remove *handler* from *tenant*."""

    @abstractmethod
    async def close(self) -> None:
        """Shutdown the bus and release resources."""


class LocalBus(BroadcastBus):
    """In-memory broadcast bus (single-instance default).

    LocalBus.publish() is a no-op — the in-process broadcast already
    happens via ConnectionHub._broadcast_local(). This class exists so
    code always calls bus.publish() without an ``if bus is not None``
    branch, as specified in DESIGN-phase14plus.md §B.3.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[BroadcastHandler]] = {}

    async def publish(
        self, tenant: str, message: dict[str, Any],
        exclude: list[str] | None = None,
    ) -> None:
        """No-op: local broadcast is handled by ConnectionHub._broadcast_local()."""
        logger.debug(
            "LocalBus.publish() no-op for tenant=%s (local delivery already done)",
            tenant,
        )

    async def subscribe(
        self, tenant: str, handler: BroadcastHandler,
    ) -> None:
        self._subscribers.setdefault(tenant, set()).add(handler)

    async def unsubscribe(
        self, tenant: str, handler: BroadcastHandler,
    ) -> None:
        subs = self._subscribers.get(tenant)
        if subs is not None:
            subs.discard(handler)
            if not subs:
                del self._subscribers[tenant]

    async def close(self) -> None:
        self._subscribers.clear()
