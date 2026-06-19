"""MCP session storage mixin — Phase 16.4c.

Provides CRUD for the mcp_sessions table that persists
the agent_id <-> mcp_session_id mapping across restarts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def upsert_mcp_session(
    db: Any, dialect: Any,
    mcp_session_id: str, agent_id: str,
    transport_type: str = "streamable-http",
) -> None:
    """Insert or update an MCP session record."""
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        """INSERT INTO mcp_sessions
               (mcp_session_id, agent_id, connected_at,
                last_activity_at, transport_type)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(mcp_session_id) DO UPDATE SET
               agent_id = excluded.agent_id,
               last_activity_at = excluded.last_activity_at""",
        [mcp_session_id, agent_id, now, now, transport_type],
    )
    await db.execute(sql, params)
    await db.commit()


async def get_mcp_session_by_agent(
    db: Any, dialect: Any, agent_id: str,
) -> Optional[dict]:
    """Get the latest MCP session for an agent."""
    sql, params = dialect.render(
        """SELECT * FROM mcp_sessions
           WHERE agent_id = ?
           ORDER BY last_activity_at DESC LIMIT 1""",
        [agent_id],
    )
    async with db.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else None


async def get_mcp_session_by_id(
    db: Any, dialect: Any, mcp_session_id: str,
) -> Optional[dict]:
    """Get an MCP session by its session ID."""
    sql, params = dialect.render(
        "SELECT * FROM mcp_sessions WHERE mcp_session_id = ?",
        [mcp_session_id],
    )
    async with db.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else None


async def update_mcp_session_activity(
    db: Any, dialect: Any, mcp_session_id: str,
) -> None:
    """Update last_activity_at for heartbeat tracking."""
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        """UPDATE mcp_sessions
           SET last_activity_at = ?
           WHERE mcp_session_id = ?""",
        [now, mcp_session_id],
    )
    await db.execute(sql, params)
    await db.commit()


async def delete_mcp_session(
    db: Any, dialect: Any, mcp_session_id: str,
) -> None:
    """Remove an MCP session record (on disconnect)."""
    sql, params = dialect.render(
        "DELETE FROM mcp_sessions WHERE mcp_session_id = ?",
        [mcp_session_id],
    )
    await db.execute(sql, params)
    await db.commit()


async def delete_stale_mcp_sessions(
    db: Any, dialect: Any, timeout_seconds: int = 300,
) -> int:
    """Remove sessions with no activity for timeout_seconds.

    Returns the number of removed sessions.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - timeout_seconds
    sql, params = dialect.render(
        """DELETE FROM mcp_sessions
           WHERE unixepoch(last_activity_at) < ?""",
        [cutoff],
    )
    cursor = await db.execute(sql, params)
    await db.commit()
    return cursor.rowcount
