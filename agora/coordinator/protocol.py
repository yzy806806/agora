"""Protocol version negotiation for WebSocket connections.

Phase 14+.E.2: On connect, the coordinator sends a WELCOME message
that includes the maximum protocol version it supports and its
capabilities.  The agent may respond with a CAPABILITIES message
to select its preferred version (≤ server max) and declare
structured capabilities.

v1 agents that do not send CAPABILITIES continue to work unchanged;
they are implicitly on protocol version 1.
"""
from __future__ import annotations

import logging
import secrets
from typing import Any

from .models import MessageType

logger = logging.getLogger(__name__)

# Supported protocol versions (major.minor → float)
SUPPORTED_VERSIONS = [1.0, 2.0]
DEFAULT_VERSION = 2.0


def build_welcome(
    agent_id: str,
    tenant_id: str = "default",
    server_version: str = "0.1.0",
    max_protocol_version: float = DEFAULT_VERSION,
    session_token: str = "",
) -> dict[str, Any]:
    """Build the WELCOME message sent immediately after WS connect.

    The payload is designed so that v1 agents can safely ignore the
    new fields (protocol_version, server_capabilities, session_token)
    and still use the existing config block.
    """
    if not session_token:
        session_token = f"sess-{secrets.token_hex(12)}"

    return {
        "type": MessageType.WELCOME,
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "protocol_version": max_protocol_version,
        "server_version": server_version,
        "session_id": session_token,
        "server_capabilities": _server_capabilities(),
        "payload": {},  # filled by caller with agent config
    }


def _server_capabilities() -> dict[str, Any]:
    """Return the coordinator's own capability advertisement."""
    return {
        "discussion": True,
        "task_execution": True,
        "workspace": True,
        "webhooks": True,
    }


def negotiate_version(
    client_version: float,
    server_max: float = DEFAULT_VERSION,
) -> float:
    """Determine the effective protocol version.

    Returns the lesser of the client's requested version and the
    server's maximum.  Falls back to 1.0 if negotiation fails.
    """
    if client_version <= 0:
        logger.warning(
            "Invalid client version %.1f, falling back to v1",
            client_version,
        )
        return 1.0
    version = min(client_version, server_max)
    # Snap to a known version
    known = sorted(SUPPORTED_VERSIONS)
    for v in known:
        if version <= v:
            return v
    # Client wants something higher than we support
    return known[-1]


def parse_version(raw: Any) -> float:
    """Safely parse a protocol version from a WS message."""
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw)
        except ValueError:
            return 0.0
    return 0.0
