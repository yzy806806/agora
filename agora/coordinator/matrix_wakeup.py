"""Matrix wakeup bridge for Agora — Phase 19+.

When an agent is offline (no active MCP session), Agora sends
a Matrix message to wake them up. The agent's Hermes instance
receives the Matrix message via its Matrix gateway and is prompted
to call ``fetch_pending_notifications`` to pull queued tasks.

Architecture:
  Agora task assigned → agent offline? → enqueue in DB
  → Matrix message in #agora-wakeup: "@agent:server You have N pending tasks"
  → Hermes Matrix gateway receives @mention → fetches pending tasks via MCP

Uses the ``matrix-nio`` library which is lighter than ``mautrix`` and
does not require a crypto store for unencrypted room messaging.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Module-level client for reuse
_client: Optional["AsyncClient"] = None
_client_task: Optional[asyncio.Task] = None
_configured: bool = False
_homeserver_url: str = ""
_access_token: str = ""
_room_id: str = ""
_bot_user_id: str = ""


def _get_nio_client() -> type:
    """Lazy-import matrix-nio client classes."""
    # matrix-nio is a pure-Python Matrix client library
    # pip install matrix-nio
    from nio import AsyncClient, MatrixRoom, RoomMessageText, Api
    return AsyncClient, MatrixRoom, RoomMessageText, Api


def configure_matrix(
    homeserver_url: str,
    access_token: str,
    room_id: str,
    bot_user_id: str = "",
) -> None:
    """Configure the Matrix wakeup client.

    Args:
        homeserver_url: e.g. "https://matrix.example.org"
        access_token: Matrix access token for the Agora bot account
        room_id: The wakeup room ID (e.g. "!abc123:matrix.example.org")
        bot_user_id: The bot's Matrix user ID (e.g. "@agora-bot:matrix.example.org")
    """
    global _configured, _homeserver_url, _access_token, _room_id, _bot_user_id
    _homeserver_url = homeserver_url
    _access_token = access_token
    _room_id = room_id
    _bot_user_id = bot_user_id or _resolve_bot_user_id(homeserver_url, access_token)
    _configured = True
    logger.info(
        "Matrix wakeup configured: homeserver=%s room=%s bot=%s",
        homeserver_url, room_id, _bot_user_id,
    )


def _resolve_bot_user_id(homeserver_url: str, access_token: str) -> str:
    """Best-effort extract user ID from access token.

    Matrix access tokens that follow the syt_ prefix convention
    can't be decoded. But we can try to resolve via /whoami.
    Will be resolved properly at connect time.
    """
    return ""  # resolved at connect time


async def _get_client() -> "AsyncClient":
    """Get or create the Matrix async client, ensuring we're connected."""
    global _client, _bot_user_id

    AsyncClient = _get_nio_client()[0]

    if _client is not None:
        return _client

    if not _configured:
        logger.debug("Matrix not configured, cannot create client")
        raise RuntimeError("Matrix wakeup not configured")

    _client = AsyncClient(_homeserver_url, _bot_user_id or "agora-bot")

    # Restore login using access token (no password needed)
    if _access_token:
        try:
            _client.restore_login(
                user_id=_bot_user_id or "@agora-bot:agora.local",
                device_id="AGORA-BOT",
                access_token=_access_token,
            )
            logger.info("Matrix bot logged in via access token")
        except Exception as exc:
            logger.warning("Failed to restore Matrix login: %s", exc)
            await _client.close()
            _client = None
            raise RuntimeError(f"Matrix login failed: {exc}")

    # Resolve bot user ID via /whoami if not known
    if not _bot_user_id:
        try:
            whoami_resp = await _client.whoami()
            if whoami_resp.user_id:
                _bot_user_id = whoami_resp.user_id
                logger.info("Matrix bot user ID resolved: %s", _bot_user_id)
        except Exception:
            logger.warning("Failed to resolve Matrix bot user ID via /whoami")

    # Join the wakeup room (idempotent)
    try:
        join_resp = await _client.join(_room_id)
        if hasattr(join_resp, "room_id"):
            logger.info("Joined Matrix wakeup room: %s", _room_id)
        else:
            logger.warning(
                "Matrix join room response unexpected: %s",
                join_resp,
            )
    except Exception as exc:
        logger.warning("Failed to join Matrix wakeup room %s: %s", _room_id, exc)

    return _client


async def send_wakeup_message(
    agent_matrix_id: str,
    agent_name: str,
    pending_count: int,
    pending_summary: list[str] | None = None,
) -> bool:
    """Send a Matrix wakeup message @mentioning the target agent.

    Returns True if sent successfully, False otherwise.
    """
    if not _configured:
        logger.debug("Matrix not configured, skipping wakeup")
        return False

    if not agent_matrix_id:
        logger.debug("No matrix_user_id for agent %s, skipping wakeup", agent_name)
        return False

    if not _room_id:
        logger.debug("No matrix_wakeup_room_id configured, skipping wakeup")
        return False

    # Build message — use Matrix Markdown (no heading, limited Markdown)
    lines = [
        f'<a href="https://matrix.to/#/{agent_matrix_id}">{agent_name}</a>',
        f"🔔 <strong>Agora Wakeup</strong>",
        "<br/>",
        f"You have <strong>{pending_count}</strong> pending notification(s) in Agora.",
        "<br/>",
    ]

    if pending_summary:
        for i, summary in enumerate(pending_summary[:5], 1):
            lines.append(f"{i}. {_html_escape(summary)}<br/>")
        if len(pending_summary) > 5:
            lines.append(f"  ... and {len(pending_summary) - 5} more<br/>")
        lines.append("<br/>")

    lines.extend([
        "Run <code>fetch_pending_notifications</code> via MCP to claim your tasks.",
        "<br/>",
        f"<em>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</em>",
    ])

    formatted_body = "".join(lines)

    # Plain-text fallback body
    plain_lines = [
        f"{agent_name}: Agora Wakeup",
        "",
        f"You have {pending_count} pending notification(s) in Agora.",
        "",
    ]
    if pending_summary:
        for i, summary in enumerate(pending_summary[:5], 1):
            plain_lines.append(f"{i}. {summary}")
        if len(pending_summary) > 5:
            plain_lines.append(f"  ... and {len(pending_summary) - 5} more")
        plain_lines.append("")
    plain_lines.extend([
        "Run fetch_pending_notifications via MCP to claim your tasks.",
        "",
        f"-- {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
    ])
    plain_body = "\n".join(plain_lines)

    try:
        client = await _get_client()
        from nio import RoomSendResponse

        # Send formatted message with @mention
        content = {
            "msgtype": "m.text",
            "body": plain_body,
            "format": "org.matrix.custom.html",
            "formatted_body": formatted_body,
            "m.mentions": {
                "user_ids": [agent_matrix_id],
            },
        }

        response = await client.room_send(
            room_id=_room_id,
            message_type="m.room.message",
            content=content,
        )

        if isinstance(response, RoomSendResponse):
            logger.info(
                "Sent Matrix wakeup to agent %s (user=%s room=%s event_id=%s)",
                agent_name, agent_matrix_id, _room_id, response.event_id,
            )
            return True
        else:
            logger.warning(
                "Matrix wakeup failed for agent %s: %s",
                agent_name, response,
            )
            return False

    except Exception as exc:
        logger.warning("Matrix wakeup error for agent %s: %s", agent_name, exc)
        return False


async def try_wakeup_agent(
    storage: Any,
    agent_id: str,
    notification_type: str,
    payload: dict,
) -> bool:
    """Try to wake up an agent via Matrix if they're offline.

    Called from MCPNotificationBridge when an agent has no active session.

    Returns True if wakeup was attempted (not guaranteed delivered).
    """
    if not _configured:
        logger.debug("Matrix not configured, cannot wake up agent %s", agent_id)
        return False

    # Check if agent has matrix_user_id configured
    agent = await storage.get_agent(agent_id)
    if not agent:
        logger.debug("Agent %s not found in storage", agent_id)
        return False

    matrix_user_id = agent.get("matrix_user_id")
    if not matrix_user_id:
        logger.debug("Agent %s has no matrix_user_id, cannot wake up", agent_id)
        return False

    # Count pending notifications for this agent
    async with storage._connection() as db:
        from .storage.pending_notifications import count_pending_for_agent
        pending_count = await count_pending_for_agent(db, storage.dialect, agent_id)

    # Build summary from the payload
    summary_lines = []
    if notification_type == "notifications/task_assigned":
        title = payload.get("title", payload.get("task_id", "Unknown task"))
        summary_lines.append(f"📋 Task assigned: {title}")
    elif notification_type == "notifications/discussion_message":
        sender = payload.get("sender_id", "Unknown")
        msg_preview = (payload.get("message", "") or "")[:80]
        summary_lines.append(f"💬 Message from {sender}: {msg_preview}")
    elif notification_type == "notifications/pipeline_event":
        stage = payload.get("stage", "Unknown")
        summary_lines.append(f"🔄 Pipeline: {stage}")
    else:
        summary_lines.append(f"📨 {notification_type}")

    agent_name = agent.get("name", agent_id)
    return await send_wakeup_message(
        agent_matrix_id=matrix_user_id,
        agent_name=agent_name,
        pending_count=pending_count + 1,  # include the current one
        pending_summary=summary_lines,
    )


async def close() -> None:
    """Close the Matrix client and cancel background task."""
    global _client, _client_task
    if _client_task is not None:
        _client_task.cancel()
        try:
            await _client_task
        except asyncio.CancelledError:
            pass
        _client_task = None
    if _client is not None:
        await _client.close()
        _client = None
        logger.info("Matrix wakeup client closed")


def _html_escape(text: str) -> str:
    """Minimal HTML escaping for Matrix formatted messages."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
