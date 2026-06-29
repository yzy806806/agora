"""Pending notifications storage — Phase 19.

Provides CRUD for the pending_notifications table, which acts as
an offline message queue for agents that don't have an active MCP session.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def add_pending_notification(
    db: Any,
    dialect: Any,
    agent_id: str,
    notification_type: str,
    payload: dict,
    ttl_minutes: int = 30,
) -> str:
    """Queue a notification for an agent (online or offline).

    Returns the notification ID.
    """
    notif_id = f"pn-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    expires = (
        datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    ).isoformat() if ttl_minutes > 0 else None

    payload_json = json.dumps(payload, ensure_ascii=False)
    sql, params = dialect.render(
        """INSERT INTO pending_notifications
           (id, agent_id, notification_type, payload, status, created_at, expires_at)
           VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
        [notif_id, agent_id, notification_type, payload_json, now, expires],
    )
    await db.execute(sql, params)
    await db.commit()
    logger.debug("Queued notification %s for agent %s (type=%s)", notif_id, agent_id, notification_type)
    return notif_id


async def get_pending_notifications(
    db: Any,
    dialect: Any,
    agent_id: str,
    limit: int = 20,
) -> list[dict]:
    """Get pending (undelivered) notifications for an agent."""
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        """SELECT id, agent_id, notification_type, payload, status,
                  created_at, delivered_at, expires_at, retry_count
           FROM pending_notifications
           WHERE agent_id = ? AND status = 'pending'
             AND (expires_at IS NULL OR expires_at > ?)
           ORDER BY created_at ASC
           LIMIT ?""",
        [agent_id, now, limit],
    )
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()

    results = []
    for row in rows:
        try:
            payload = json.loads(row[3]) if isinstance(row[3], str) else row[3]
        except (json.JSONDecodeError, TypeError):
            payload = {}
        results.append({
            "id": row[0],
            "agent_id": row[1],
            "notification_type": row[2],
            "payload": payload,
            "status": row[4],
            "created_at": row[5],
            "delivered_at": row[6],
            "expires_at": row[7],
            "retry_count": row[8],
        })
    return results


async def mark_notification_delivered(
    db: Any,
    dialect: Any,
    notif_id: str,
) -> None:
    """Mark a notification as delivered (SSE push succeeded)."""
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        "UPDATE pending_notifications SET status='delivered', delivered_at=? WHERE id=?",
        [now, notif_id],
    )
    await db.execute(sql, params)
    await db.commit()


async def mark_notification_acked(
    db: Any,
    dialect: Any,
    notif_id: str,
) -> None:
    """Mark a notification as acknowledged by the agent."""
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        "UPDATE pending_notifications SET status='acked', acked_at=? WHERE id=?",
        [now, notif_id],
    )
    await db.execute(sql, params)
    await db.commit()


async def increment_retry(
    db: Any,
    dialect: Any,
    notif_id: str,
) -> bool:
    """Increment retry count. Returns False if max retries exceeded."""
    sql, params = dialect.render(
        """UPDATE pending_notifications
           SET retry_count = retry_count + 1
           WHERE id = ?
           RETURNING retry_count, max_retries""",
        [notif_id],
    )
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()

    if row is None:
        return False

    retry_count, max_retries = row[0], row[1]
    if retry_count >= max_retries:
        expire_sql, expire_params = dialect.render(
            "UPDATE pending_notifications SET status='expired' WHERE id=?",
            [notif_id],
        )
        await db.execute(expire_sql, expire_params)
        await db.commit()
        return False

    await db.commit()
    return True


async def get_expired_assignments(
    db: Any,
    dialect: Any,
    timeout_minutes: int = 10,
) -> list[dict]:
    """Get task-assigned notifications that haven't been acked within timeout."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
    ).isoformat()

    sql, params = dialect.render(
        """SELECT id, agent_id, payload
           FROM pending_notifications
           WHERE notification_type = 'notifications/task_assigned'
             AND status = 'delivered'
             AND acked_at IS NULL
             AND delivered_at < ?
           ORDER BY created_at ASC""",
        [cutoff],
    )
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()

    results = []
    for row in rows:
        try:
            payload = json.loads(row[2]) if isinstance(row[2], str) else row[2]
        except (json.JSONDecodeError, TypeError):
            payload = {}
        results.append({
            "notif_id": row[0],
            "agent_id": row[1],
            "payload": payload,
        })
    return results


async def count_pending_for_agent(
    db: Any,
    dialect: Any,
    agent_id: str,
) -> int:
    """Count pending notifications for an agent."""
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        """SELECT COUNT(*) FROM pending_notifications
           WHERE agent_id = ? AND status = 'pending'
             AND (expires_at IS NULL OR expires_at > ?)""",
        [agent_id, now],
    )
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return row[0] if row else 0
