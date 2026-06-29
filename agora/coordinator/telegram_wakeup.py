"""Telegram wakeup bridge for Agora — Phase 19.

When an agent is offline (no active MCP session), Agora sends
a Telegram message to wake them up. The agent's Hermes instance
receives the Telegram message and is prompted to call
``fetch_pending_notifications`` to pull queued tasks.

Architecture:
  Agora task assigned → agent offline? → enqueue in DB
  → Telegram message: "You have N pending tasks in Agora"
  → Hermes receives Telegram message → fetches pending tasks via MCP
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote as url_quote

import httpx

logger = logging.getLogger(__name__)

# Module-level client for reuse
_client: Optional[httpx.AsyncClient] = None
_bot_token: Optional[str] = None


def configure_telegram(bot_token: str) -> None:
    """Configure the Telegram bot token for wakeup messages."""
    global _bot_token
    _bot_token = bot_token
    logger.info("Telegram wakeup configured (bot token set)")


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    return _client


async def send_wakeup_message(
    chat_id: str,
    agent_name: str,
    pending_count: int,
    pending_summary: list[str] | None = None,
) -> bool:
    """Send a Telegram wakeup message to an agent.

    Returns True if sent successfully, False otherwise.
    """
    if not _bot_token:
        logger.debug("Telegram bot token not configured, skipping wakeup")
        return False

    if not chat_id:
        logger.debug("No telegram_chat_id for agent %s, skipping wakeup", agent_name)
        return False

    # Build message
    lines = [
        f"🔔 *Agora Wakeup* — {agent_name}",
        "",
        f"You have *{pending_count}* pending notification(s) in Agora.",
        "",
    ]
    if pending_summary:
        for i, summary in enumerate(pending_summary[:5], 1):
            lines.append(f"{i}. {summary}")
        if len(pending_summary) > 5:
            lines.append(f"  ... and {len(pending_summary) - 5} more")
        lines.append("")

    lines.extend([
        "Run `fetch_pending_notifications` via MCP to claim your tasks.",
        "",
        f"_{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
    ])

    text = "\n".join(lines)

    try:
        client = await _get_client()
        url = f"https://api.telegram.org/bot{_bot_token}/sendMessage"
        response = await client.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        })
        if response.status_code == 200:
            logger.info("Sent Telegram wakeup to agent %s (chat %s)", agent_name, chat_id)
            return True
        else:
            logger.warning(
                "Telegram wakeup failed for agent %s: HTTP %d %s",
                agent_name, response.status_code, response.text[:200],
            )
            return False
    except Exception as exc:
        logger.warning("Telegram wakeup error for agent %s: %s", agent_name, exc)
        return False


async def try_wakeup_agent(
    storage: Any,
    agent_id: str,
    notification_type: str,
    payload: dict,
) -> bool:
    """Try to wake up an agent via Telegram if they're offline.

    Called from MCPNotificationBridge when an agent has no active session.

    Returns True if wakeup was attempted (not guaranteed delivered).
    """
    # Check if agent has telegram_chat_id configured
    agent = await storage.get_agent(agent_id)
    if not agent:
        logger.debug("Agent %s not found in storage", agent_id)
        return False

    chat_id = agent.get("telegram_chat_id")
    if not chat_id:
        logger.debug("Agent %s has no telegram_chat_id, cannot wake up", agent_id)
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
        chat_id=chat_id,
        agent_name=agent_name,
        pending_count=pending_count + 1,  # include the current one
        pending_summary=summary_lines,
    )
