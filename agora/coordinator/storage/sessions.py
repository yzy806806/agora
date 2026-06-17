"""Session record CRUD — backend-agnostic."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect

logger = logging.getLogger(__name__)


async def create_session(
    db: Any, dialect: Dialect,
    agent_id: str, project_id: str = "default",
    session_type: str = "task_execution",
    started_at: str | None = None, ended_at: str | None = None,
    input_messages: list | None = None,
    output_messages: list | None = None,
    tool_calls: list | None = None, errors: list | None = None,
    outcome: str = "success", metadata: dict | None = None,
) -> dict:
    sid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    if started_at is None:
        started_at = now
    row = {
        "id": sid, "agent_id": agent_id,
        "project_id": project_id,
        "session_type": session_type,
        "started_at": started_at, "ended_at": ended_at,
        "input_messages": json.dumps(input_messages or []),
        "output_messages": json.dumps(output_messages or []),
        "tool_calls": json.dumps(tool_calls or []),
        "errors": json.dumps(errors or []),
        "outcome": outcome,
        "metadata": json.dumps(metadata or {}),
        "notes": json.dumps([]),
    }
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["?"] * len(row))
    sql, params = dialect.render(
        f"INSERT INTO session_records ({cols}) "
        f"VALUES ({placeholders})", list(row.values()))
    await db.execute(sql, params)
    await db.commit()
    return _to_dict(row)


async def get_session(
    db: Any, dialect: Dialect, session_id: str,
) -> Optional[dict]:
    sql, params = dialect.render(
        "SELECT * FROM session_records WHERE id = ?", [session_id])
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return _row_to_dict(row) if row else None


async def list_sessions(
    db: Any, dialect: Dialect,
    agent_id: str | None = None,
    project_id: str | None = None,
    limit: int = 100, offset: int = 0,
) -> list[dict]:
    clauses, params = [], []
    if agent_id is not None:
        clauses.append("agent_id = ?"); params.append(agent_id)
    if project_id is not None:
        clauses.append("project_id = ?"); params.append(project_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])
    sql, params = dialect.render(
        f"SELECT * FROM session_records {where} "
        "ORDER BY started_at DESC LIMIT ? OFFSET ?", params)
    async with db.execute(sql, params) as cur:
        rows = [row async for row in cur]
    return [_row_to_dict(r) for r in rows]


async def add_note(
    db: Any, dialect: Dialect,
    session_id: str, author: str, content: str,
    tags: list[str] | None = None,
) -> Optional[dict]:
    session = await get_session(db, dialect, session_id)
    if session is None:
        return None
    notes = session.get("notes", [])
    notes.append({
        "author": author, "content": content,
        "tags": tags or [],
        "at": datetime.now(timezone.utc).isoformat(),
    })
    sql, params = dialect.render(
        "UPDATE session_records SET notes = ? WHERE id = ?",
        [json.dumps(notes), session_id])
    await db.execute(sql, params)
    await db.commit()
    session["notes"] = notes
    return session


async def update_session(
    db: Any, dialect: Dialect,
    session_id: str, updates: dict,
) -> Optional[dict]:
    session = await get_session(db, dialect, session_id)
    if session is None:
        return None
    allowed = {
        "ended_at", "outcome", "session_type",
        "input_messages", "output_messages",
        "tool_calls", "errors", "metadata",
    }
    sets, params = [], []
    for k, v in updates.items():
        if k not in allowed:
            continue
        if isinstance(v, (list, dict)):
            v = json.dumps(v)
        sets.append(f"{k} = ?"); params.append(v)
    if not sets:
        return session
    params.append(session_id)
    sql, params = dialect.render(
        f"UPDATE session_records SET {', '.join(sets)} "
        "WHERE id = ?", params)
    await db.execute(sql, params)
    await db.commit()
    return await get_session(db, dialect, session_id)


def _to_dict(row: dict) -> dict:
    d = dict(row)
    for k in ("input_messages", "output_messages",
              "tool_calls", "errors", "notes"):
        if k in d and isinstance(d[k], str):
            d[k] = json.loads(d[k])
    if "metadata" in d and isinstance(d["metadata"], str):
        d["metadata"] = json.loads(d["metadata"])
    return d


def _row_to_dict(row: Any) -> dict:
    d = dict(row)
    return _to_dict(d)
