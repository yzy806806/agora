"""SQLite storage for Agora motions, messages, and votes.

Database lives at ~/.hermes/agora/motions.db — co-located with Hermes
data so it travels with the profile.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _agora_db_path() -> Path:
    """Return the path to the Agora motions database.

    Uses the GLOBAL Hermes home (not profile-scoped) so that workers
    running under different profiles all read/write the same motions DB.
    The kanban DB is already global, and motions must be too.
    """
    import os
    kanban_db = os.environ.get("HERMES_KANBAN_DB", "")
    if kanban_db:
        global_root = Path(kanban_db).parent
    else:
        try:
            from hermes_constants import get_hermes_home
            home = Path(get_hermes_home())
            if home.parent.name == "profiles":
                global_root = home.parent.parent
            else:
                global_root = home
        except Exception:
            global_root = Path.home() / ".hermes"
    agora_dir = global_root / "agora"
    agora_dir.mkdir(parents=True, exist_ok=True)
    return agora_dir / "motions.db"


def _connect() -> sqlite3.Connection:
    """Open a connection to the Agora DB and ensure schema exists."""
    db_path = _agora_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist, and migrate existing ones."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS motions (
            id              TEXT PRIMARY KEY,
            title           TEXT NOT NULL,
            description     TEXT DEFAULT '',
            status          TEXT DEFAULT 'discussing',
            decision        TEXT,
            rationale       TEXT,
            action_items    TEXT DEFAULT '[]',
            current_round   INTEGER DEFAULT 0,
            max_rounds      INTEGER DEFAULT 3,
            source          TEXT DEFAULT 'user',
            source_task_id  TEXT,
            source_profile  TEXT,
            blocking        INTEGER DEFAULT 0,
            participants    TEXT DEFAULT '["architect","developer","reviewer"]',
            created_at      TEXT,
            closed_at       TEXT
        );

        CREATE TABLE IF NOT EXISTS messages (
            id          TEXT PRIMARY KEY,
            motion_id   TEXT NOT NULL,
            role        TEXT NOT NULL,
            round_num   INTEGER DEFAULT 1,
            stance      TEXT DEFAULT 'neutral',
            content     TEXT NOT NULL,
            timestamp   TEXT,
            FOREIGN KEY (motion_id) REFERENCES motions(id)
        );

        CREATE TABLE IF NOT EXISTS votes (
            id          TEXT PRIMARY KEY,
            motion_id   TEXT NOT NULL,
            role        TEXT NOT NULL,
            vote        TEXT NOT NULL,
            reason      TEXT DEFAULT '',
            confidence  REAL DEFAULT 0.8,
            timestamp   TEXT,
            FOREIGN KEY (motion_id) REFERENCES motions(id)
        );

        CREATE TABLE IF NOT EXISTS discussion_state (
            motion_id      TEXT PRIMARY KEY,
            current_state  TEXT DEFAULT 'discussing',
            next_speaker   TEXT,
            last_guidance  TEXT,
            last_action    TEXT,
            updated_at     TEXT,
            FOREIGN KEY (motion_id) REFERENCES motions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_messages_motion ON messages(motion_id);
        CREATE INDEX IF NOT EXISTS idx_votes_motion ON votes(motion_id);
    """)
    conn.commit()

    # --- Schema migration: add new columns if they don't exist ---
    _migrate_add_columns(conn)


def _migrate_add_columns(conn: sqlite3.Connection) -> None:
    """Safely add new columns to existing tables (idempotent)."""

    def _has_column(table: str, col: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r[1] == col for r in rows)

    # motions: event-driven fields
    motion_cols = {
        "chair": "TEXT",
        "state": "TEXT DEFAULT 'discussing'",
        "step_count": "INTEGER DEFAULT 0",
        "max_steps": "INTEGER DEFAULT 30",
    }
    for col, typedef in motion_cols.items():
        if not _has_column("motions", col):
            conn.execute(f"ALTER TABLE motions ADD COLUMN {col} {typedef}")

    # messages: event-driven fields
    msg_cols = {
        "target_role": "TEXT",
        "is_chair": "INTEGER DEFAULT 0",
        "step_type": "TEXT DEFAULT 'speak'",
    }
    for col, typedef in msg_cols.items():
        if not _has_column("messages", col):
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {typedef}")

    # motions: project association
    if not _has_column("motions", "project"):
        conn.execute("ALTER TABLE motions ADD COLUMN project TEXT DEFAULT ''")

    conn.commit()


# ---------------------------------------------------------------------------
# Motion CRUD
# ---------------------------------------------------------------------------

def create_motion(
    title: str,
    description: str = "",
    max_rounds: int = 3,
    source: str = "user",
    source_task_id: str = "",
    blocking: bool = False,
    participants: list[str] | None = None,
    chair: str = "",
    max_steps: int = 30,
    project: str = "",
) -> dict:
    """Create a new motion record. Returns the motion dict."""
    motion_id = f"motion-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    participants = participants or ["architect", "developer", "reviewer"]

    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO motions
               (id, title, description, max_rounds, source, source_task_id,
                source_profile, blocking, participants, created_at,
                chair, state, step_count, max_steps, project)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (motion_id, title, description, max_rounds, source,
             source_task_id or None, None,
             1 if blocking else 0, json.dumps(participants), now,
             chair, "discussing", 0, max_steps, project),
        )
        conn.commit()
    finally:
        conn.close()

    return get_motion(motion_id)  # type: ignore


def get_motion(motion_id: str) -> Optional[dict]:
    """Fetch a single motion by ID."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM motions WHERE id = ?", (motion_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_motion(dict(row))
    finally:
        conn.close()


def list_motions(
    status_filter: str = "all",
    limit: int = 20,
) -> list[dict]:
    """List motions, optionally filtered by status."""
    conn = _connect()
    try:
        if status_filter == "active":
            rows = conn.execute(
                "SELECT * FROM motions WHERE status NOT IN ('closed') "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        elif status_filter == "closed":
            rows = conn.execute(
                "SELECT * FROM motions WHERE status = 'closed' "
                "ORDER BY closed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM motions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_motion(dict(r)) for r in rows]
    finally:
        conn.close()


def update_motion_status(
    motion_id: str,
    status: str,
    decision: str = "",
    rationale: str = "",
    action_items: list[str] | None = None,
) -> None:
    """Update a motion's status and closing fields."""
    conn = _connect()
    try:
        fields = ["status = ?"]
        params: list[Any] = [status]

        if decision:
            fields.append("decision = ?")
            params.append(decision)
        if rationale:
            fields.append("rationale = ?")
            params.append(rationale)
        if action_items is not None:
            fields.append("action_items = ?")
            params.append(json.dumps(action_items))
        if status == "closed":
            fields.append("closed_at = ?")
            params.append(datetime.now(timezone.utc).isoformat())
            # Keep state in sync with status when closing
            fields.append("state = ?")
            params.append("closed")

        params.append(motion_id)
        conn.execute(
            f"UPDATE motions SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Messages — see bottom of file for extended add_message with event-driven fields
# --------------------------------------------------------------------------- #

def get_messages(motion_id: str, round_num: int | None = None) -> list[dict]:
    """Fetch messages for a motion, optionally filtered by round."""
    conn = _connect()
    try:
        if round_num is not None:
            rows = conn.execute(
                "SELECT * FROM messages WHERE motion_id = ? AND round_num = ? "
                "ORDER BY timestamp ASC",
                (motion_id, round_num),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM messages WHERE motion_id = ? "
                "ORDER BY timestamp ASC",
                (motion_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Votes
# ---------------------------------------------------------------------------

def add_vote(
    motion_id: str,
    role: str,
    vote: str,
    reason: str = "",
    confidence: float = 0.8,
) -> str:
    """Record a vote. Returns the vote ID."""
    vote_id = f"vote-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO votes
               (id, motion_id, role, vote, reason, confidence, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (vote_id, motion_id, role, vote, reason, confidence, now),
        )
        conn.commit()
    finally:
        conn.close()
    return vote_id


def get_votes(motion_id: str) -> list[dict]:
    """Fetch all votes for a motion."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM votes WHERE motion_id = ? ORDER BY timestamp ASC",
            (motion_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_motion(row: dict) -> dict:
    """Convert a DB row to a motion dict with parsed JSON fields."""
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row.get("description", ""),
        "status": row.get("status", "discussing"),
        "decision": row.get("decision"),
        "rationale": row.get("rationale"),
        "action_items": json.loads(row.get("action_items", "[]")),
        "current_round": row.get("current_round", 0),
        "max_rounds": row.get("max_rounds", 3),
        "source": row.get("source", "user"),
        "source_task_id": row.get("source_task_id"),
        "source_profile": row.get("source_profile"),
        "blocking": bool(row.get("blocking", 0)),
        "participants": json.loads(row.get("participants", "[]")),
        "created_at": row.get("created_at"),
        "closed_at": row.get("closed_at"),
        # Event-driven fields
        "chair": row.get("chair", ""),
        "state": row.get("state", "discussing"),
        "step_count": row.get("step_count", 0),
        "max_steps": row.get("max_steps", 30),
        "project": row.get("project", ""),
    }


# --------------------------------------------------------------------------- #
#  Event-driven state (discussion_state table)                                #
# --------------------------------------------------------------------------- #

def get_discussion_state(motion_id: str) -> dict | None:
    """Get the current event-driven discussion state for a motion."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM discussion_state WHERE motion_id = ?",
            (motion_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def save_discussion_state(
    motion_id: str,
    current_state: str,
    next_speaker: str | None = None,
    last_guidance: str | None = None,
    last_action: str | None = None,
) -> None:
    """Insert or update the discussion state for a motion."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO discussion_state
               (motion_id, current_state, next_speaker, last_guidance, last_action, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(motion_id) DO UPDATE SET
                 current_state = excluded.current_state,
                 next_speaker  = excluded.next_speaker,
                 last_guidance = excluded.last_guidance,
                 last_action   = excluded.last_action,
                 updated_at    = excluded.updated_at
            """,
            (motion_id, current_state, next_speaker, last_guidance, last_action, now),
        )
        conn.commit()
    finally:
        conn.close()


def increment_step_count(motion_id: str) -> int:
    """Increment and return the step_count for a motion."""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE motions SET step_count = step_count + 1 WHERE id = ?",
            (motion_id,),
        )
        conn.commit()
        row = conn.execute(
            "SELECT step_count FROM motions WHERE id = ?", (motion_id,)
        ).fetchone()
        return dict(row)["step_count"] if row else 0
    finally:
        conn.close()


def update_motion_state(motion_id: str, state: str) -> None:
    """Update a motion's event-driven state (discussing/voting/summarizing/closed).

    When state is set to 'closed', also update status to 'closed' to keep
    the two fields consistent.
    """
    conn = _connect()
    try:
        if state == "closed":
            conn.execute(
                "UPDATE motions SET state = ?, status = 'closed', closed_at = COALESCE(closed_at, ?) WHERE id = ?",
                (state, datetime.now(timezone.utc).isoformat(), motion_id),
            )
        else:
            conn.execute(
                "UPDATE motions SET state = ? WHERE id = ?",
                (state, motion_id),
            )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
#  Messages (extended for event-driven fields)                               #
# --------------------------------------------------------------------------- #

def add_message(
    motion_id: str,
    role: str,
    round_num: int,
    stance: str,
    content: str,
    step_type: str = "speak",
    target_role: str = "",
    is_chair: bool = False,
) -> str:
    """Add a discussion message. Returns the message ID."""
    msg_id = f"msg-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO messages
               (id, motion_id, role, round_num, stance, content, timestamp,
                step_type, target_role, is_chair)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (msg_id, motion_id, role, round_num, stance, content, now,
             step_type, target_role or None, 1 if is_chair else 0),
        )
        conn.commit()
    finally:
        conn.close()
    return msg_id
