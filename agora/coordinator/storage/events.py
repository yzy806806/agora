"""Event log storage — backend-agnostic.

Stores and queries system events (motion lifecycle,
agent connections, etc.) for the dashboard event stream.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect


async def log_event(
    db: Any, dialect: Dialect,
    event_type: str, detail: str = "",
    motion_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> int:
    """Insert a new event into the event log."""
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        """INSERT INTO events
           (type, detail, motion_id, agent_id, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        [event_type, detail, motion_id, agent_id, now],
    )
    cursor = await db.execute(sql, params)
    await db.commit()
    return cursor.lastrowid


async def get_events(
    db: Any, dialect: Dialect,
    since: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Query events with optional filters."""
    clauses: list[str] = []
    params: list = []
    if since:
        clauses.append("created_at > ?"); params.append(since)
    if event_type:
        clauses.append("type = ?"); params.append(event_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    sql, params = dialect.render(
        f"SELECT * FROM events {where} "
        "ORDER BY created_at DESC LIMIT ?", params)
    async with db.execute(sql, params) as cursor:
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_timeline(
    db: Any, dialect: Dialect, motion_id: str,
) -> list[dict]:
    """Build a discussion timeline from messages + votes + events."""
    entries: list[dict] = []
    # Status-change events
    sql1, p1 = dialect.render(
        "SELECT * FROM events WHERE motion_id = ? "
        "ORDER BY created_at", [motion_id])
    async with db.execute(sql1, p1) as cur:
        for r in await cur.fetchall():
            entries.append(dict(r))
    # Messages
    sql2, p2 = dialect.render(
        "SELECT * FROM messages WHERE motion_id = ? "
        "ORDER BY timestamp", [motion_id])
    async with db.execute(sql2, p2) as cur:
        for m in await cur.fetchall():
            d = dict(m)
            entries.append({
                "time": d.get("timestamp", ""),
                "type": "speech",
                "agent_id": d.get("agent_id"),
                "content": d.get("content", ""),
                "round_num": d.get("round_num"),
            })
    # Votes
    sql3, p3 = dialect.render(
        "SELECT * FROM votes WHERE motion_id = ? "
        "ORDER BY timestamp", [motion_id])
    async with db.execute(sql3, p3) as cur:
        for v in await cur.fetchall():
            d = dict(v)
            entries.append({
                "time": d.get("timestamp", ""),
                "type": "vote",
                "agent_id": d.get("agent_id"),
                "content": f"voted {d.get('vote', '?')} "
                           f"(confidence {d.get('confidence', 0)})",
            })
    entries.sort(key=lambda e: e.get("time", ""))
    return entries
