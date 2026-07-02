"""Worker session management — prevent session bloat.

Workers use ``--resume <session_id>`` to keep conversation context across
kanban tasks and discussions.  After many tasks the session grows large,
slowing down spawns and inflating token costs.  This module provides:

  - ``check_session_size`` — query the Hermes session DB (or fall back to
    a heuristic based on motions + kanban activity) to decide whether a
    session needs rotation.
  - ``rotate_session`` — clear the stored ``session_id`` so the next spawn
    creates a fresh session.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Rotation thresholds
_MAX_MESSAGES = 500
_MAX_SIZE_KB = 2000.0
_HEURISTIC_THRESHOLD = 100  # motions messages or completed tasks


def _state_db_path() -> Path | None:
    """Locate the Hermes state SQLite DB that stores sessions + messages."""
    candidates: list[str] = []
    kanban_db = os.environ.get("HERMES_KANBAN_DB", "")
    if kanban_db:
        candidates.append(str(Path(kanban_db).parent / "state.db"))
    candidates.append(str(Path.home() / ".hermes" / "state.db"))
    for c in candidates:
        if c and Path(c).exists():
            return Path(c)
    return None


def _query_session_db(session_id: str) -> dict | None:
    """Query the Hermes state DB for a session's message count and size.

    Returns ``None`` if the DB or session cannot be found.
    """
    db_path = _state_db_path()
    if db_path is None:
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT message_count FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            message_count = row["message_count"] or 0

            # Total size = sum of content lengths in the messages table
            size_row = conn.execute(
                "SELECT COALESCE(SUM(LENGTH(content)), 0) AS total_bytes "
                "FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            total_bytes = size_row["total_bytes"] if size_row else 0
            size_kb = round(total_bytes / 1024.0, 1)

            return {
                "message_count": message_count,
                "size_kb": size_kb,
            }
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("Failed to query session DB for %s: %s", session_id, exc)
        return None


def _heuristic_activity_count(worker_name: str) -> int:
    """Fallback heuristic: count motions messages + completed kanban tasks.

    If either exceeds the threshold the session is flagged for rotation.
    """
    count = 0

    # Count messages in the Agora motions DB attributed to this worker
    try:
        from .storage import motions as db
        # We can't easily enumerate all motions for a worker without
        # listing all motions, so just count messages with role=worker_name
        motions_db = db._agora_db_path()
        if motions_db.exists():
            conn = sqlite3.connect(str(motions_db))
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM messages WHERE role = ?",
                    (worker_name,),
                ).fetchone()
                count += row[0] if row else 0
            finally:
                conn.close()
    except Exception as exc:
        logger.debug("Heuristic motions count failed for %s: %s", worker_name, exc)

    # Count completed kanban tasks assigned to this worker
    try:
        from hermes_cli import kanban_db
        conn = kanban_db.connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM tasks WHERE assignee = ? AND status = 'done'",
                (worker_name,),
            ).fetchone()
            count += row[0] if row else 0
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("Heuristic kanban count failed for %s: %s", worker_name, exc)

    return count


def check_session_size(profile_name: str, session_id: str | None) -> dict:
    """Check if a worker's session is too large.

    Queries the Hermes session DB to get the session's message count
    and total size. Returns dict with:
      - session_id: str
      - message_count: int
      - size_kb: float
      - needs_rotation: bool  (True if > 500 messages or > 2000KB)

    If the session_id is ``None`` or the session can't be found, a
    heuristic based on motions/kanban activity is used.  If that also
    fails, ``needs_rotation`` is conservatively set to ``False``.
    """
    if not session_id:
        # Fall back to heuristic
        try:
            activity = _heuristic_activity_count(profile_name)
            return {
                "session_id": "",
                "message_count": activity,
                "size_kb": 0.0,
                "needs_rotation": activity > _HEURISTIC_THRESHOLD,
            }
        except Exception:
            return {
                "session_id": "",
                "message_count": 0,
                "size_kb": 0.0,
                "needs_rotation": False,
            }

    db_result = _query_session_db(session_id)
    if db_result is not None:
        msg_count = db_result["message_count"]
        size_kb = db_result["size_kb"]
        needs_rotation = msg_count > _MAX_MESSAGES or size_kb > _MAX_SIZE_KB
        return {
            "session_id": session_id,
            "message_count": msg_count,
            "size_kb": size_kb,
            "needs_rotation": needs_rotation,
        }

    # DB query failed — try heuristic
    try:
        activity = _heuristic_activity_count(profile_name)
        return {
            "session_id": session_id,
            "message_count": activity,
            "size_kb": 0.0,
            "needs_rotation": activity > _HEURISTIC_THRESHOLD,
        }
    except Exception:
        # Conservative: don't rotate if we can't determine size
        return {
            "session_id": session_id,
            "message_count": 0,
            "size_kb": 0.0,
            "needs_rotation": False,
        }


def rotate_session(profile_name: str, worker_name: str) -> dict:
    """Rotate a worker's session.

    Clears the session_id in the worker registry so the next spawn creates a
    fresh session. Returns dict with old_session_id and status.

    In-place compression (configured in config.yaml) handles context
    management during normal operation — session IDs persist across
    compressions. Rotation is just a safety net for edge cases where a
    session has grown too large despite compression. We don't spawn an agent
    to write a memory summary here — that's too expensive for a safety-net
    operation. The worker's MEMORY.md already accumulates experience
    organically through normal agent operation.
    """
    old_session_id: str | None = None

    # Get current session_id
    try:
        from .worker_manager import get_worker_session
        old_session_id = get_worker_session(worker_name)
    except Exception as exc:
        logger.warning("Failed to get session for %s: %s", worker_name, exc)

    if not old_session_id:
        return {
            "old_session_id": None,
            "status": "no_session",
            "message": "Worker has no session_id — nothing to rotate",
        }

    # Clear the session_id so the next spawn creates a new session
    try:
        from .worker_manager import update_worker_session
        update_worker_session(worker_name, None)
    except Exception as exc:
        logger.error("Failed to clear session for %s: %s", worker_name, exc)
        return {
            "old_session_id": old_session_id,
            "status": "error",
            "message": f"Failed to clear session: {exc}",
        }

    logger.info(
        "Session rotated for worker '%s' (old=%s)", worker_name, old_session_id,
    )
    return {
        "old_session_id": old_session_id,
        "status": "rotated",
    }
