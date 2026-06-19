"""Run loop for AgoraAgentClient.

Phase 16.10: WS run loop removed. MCP agents don't need a WS
event loop — they receive notifications via MCP SSE stream and
invoke tools via MCP POST requests.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run(client) -> None:
    """No-op: MCP agents don't need a WS event loop."""
    logger.info("MCP mode: no WS run loop needed")
