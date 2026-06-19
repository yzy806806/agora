"""AgoraAgentClient — lifecycle methods.

Phase 16.10: WS connect/disconnect removed. Agents connect via
MCP protocol. This module provides HTTP-only lifecycle helpers.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def connect(self: Any) -> None:
    """HTTP-only registration (no WS). Call register() instead."""
    logger.info("HTTP client ready for %s", self._config.coordinator_url)


async def disconnect(self: Any) -> None:
    """Close the HTTP client."""
    await self._http.aclose()


async def run(self: Any) -> None:
    """No-op: MCP agents don't need a WS event loop."""
    logger.info("MCP mode: no WS event loop needed")
