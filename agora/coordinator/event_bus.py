"""Event bus bridge — Phase 11.5a + Phase 16.4d.

Connects the coordinator's event system to:
1. Dashboard WebSocket hub for real-time push notifications
2. MCP Notification Bridge for SSE push to MCP clients

Publishes events to dashboard clients and MCP sessions.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .dashboard_ws import DashboardHub

logger = logging.getLogger(__name__)

_dashboard_hub: Optional[DashboardHub] = None
_mcp_bridge: Any = None  # MCPNotificationBridge, set via init


def init_event_bus(hub: DashboardHub) -> None:
    """Set the dashboard hub reference for event forwarding."""
    global _dashboard_hub
    _dashboard_hub = hub


def init_mcp_bridge(bridge: Any) -> None:
    """Set the MCP notification bridge for SSE push.

    Called from main.py after MCPNotificationBridge is created.
    If never called, MCP notification forwarding is a no-op.
    """
    global _mcp_bridge
    _mcp_bridge = bridge


async def publish(
    event_type: str, payload: dict[str, Any],
    channel: str = "events",
) -> int:
    """Forward an event to dashboard clients and MCP sessions.

    Returns the number of dashboard clients that received the event.
    Also triggers MCP notification forwarding as a side effect.
    """
    # 1. Dashboard push
    count = 0
    if _dashboard_hub is not None:
        count = await _dashboard_hub.broadcast_event(
            event_type, payload, channel,
        )
    # 2. MCP SSE push
    await _forward_to_mcp(event_type, payload)
    return count


async def _forward_to_mcp(
    event_type: str, payload: dict[str, Any],
) -> None:
    """Route Agora events to MCP notification methods.

    Maps internal event types to MCPNotificationBridge methods:
    - TASK_STATUS → on_task_updated
    - TASK_ASSIGNED → on_task_assigned
    - DISCUSSION_MESSAGE → on_discussion_message
    - PIPELINE_EVENT → on_pipeline_event
    """
    if _mcp_bridge is None:
        return
    try:
        if event_type == "TASK_ASSIGNED":
            await _mcp_bridge.on_task_assigned(
                task_id=payload.get("task_id", ""),
                agent_id=payload.get("agent_id", ""),
                payload=payload,
            )
        elif event_type == "TASK_STATUS":
            await _mcp_bridge.on_task_updated(
                task_id=payload.get("task_id", ""),
                old_status=payload.get("old_status", ""),
                new_status=payload.get("status", ""),
                agent_id=payload.get("agent_id", ""),
            )
        elif event_type == "DISCUSSION_MESSAGE":
            await _mcp_bridge.on_discussion_message(
                conv_id=payload.get("conversation_id", ""),
                sender_id=payload.get("sender_id", ""),
                message=payload.get("message", ""),
                timestamp=payload.get("timestamp", ""),
            )
        elif event_type == "PIPELINE_EVENT":
            await _mcp_bridge.on_pipeline_event(
                pipeline_id=payload.get("pipeline_id", ""),
                stage=payload.get("stage", ""),
                status=payload.get("status", ""),
                message=payload.get("message", ""),
            )
    except Exception:
        logger.warning(
            "MCP notification forwarding failed for %s",
            event_type, exc_info=True,
        )
