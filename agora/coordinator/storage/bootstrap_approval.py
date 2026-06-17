"""Bootstrap approval & agent CRUD — backend-agnostic."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect


async def create_approval(
    db: Any, dialect: Dialect,
    motion_id: str, decision: str, rationale: str = "",
    action_items: Optional[list[dict]] = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    items_json = json.dumps(action_items or [])
    sql, params = dialect.render(
        """INSERT INTO bootstrap_approvals
        (motion_id, decision, rationale, action_items,
         approval_status, requested_at)
        VALUES (?, ?, ?, ?, 'pending', ?)""",
        [motion_id, decision, rationale, items_json, now])
    await db.execute(sql, params)
    await db.commit()
    id_sql, id_params = dialect.render(dialect.last_insert_id_sql())
    async with db.execute(id_sql, id_params) as cur:
        row = await cur.fetchone()
    return row[0] if row else 0


async def decide_approval(
    db: Any, dialect: Dialect,
    approval_id: int, approved: bool,
    approved_by: str = "", feedback: str = "",
) -> None:
    status = "approved" if approved else "rejected"
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        """UPDATE bootstrap_approvals
        SET approval_status = ?, approved_by = ?,
            feedback = ?, processed_at = ?
        WHERE id = ?""",
        [status, approved_by, feedback, now, approval_id])
    await db.execute(sql, params)
    await db.commit()


async def get_pending_approvals(
    db: Any, dialect: Dialect, limit: int = 10,
) -> list[dict]:
    sql, params = dialect.render(
        """SELECT * FROM bootstrap_approvals
        WHERE approval_status = 'pending'
        ORDER BY requested_at ASC LIMIT ?""",
        [limit])
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def register_bootstrap_agent(
    db: Any, dialect: Dialect,
    agent_id: str, name: str, role: str,
    model: str = "", capabilities: Optional[list[str]] = None,
) -> int:
    caps_json = json.dumps(capabilities or [])
    prefix = dialect.insert_or_replace()
    sql, params = dialect.render(
        f"""{prefix} bootstrap_agents
        (agent_id, name, role, model, capabilities)
        VALUES (?, ?, ?, ?, ?)""",
        [agent_id, name, role, model, caps_json])
    await db.execute(sql, params)
    await db.commit()
    id_sql, id_params = dialect.render(dialect.last_insert_id_sql())
    async with db.execute(id_sql, id_params) as cur:
        row = await cur.fetchone()
    return row[0] if row else 0


async def list_bootstrap_agents(
    db: Any, dialect: Dialect, active_only: bool = False,
) -> list[dict]:
    query = "SELECT * FROM bootstrap_agents"
    params: list = []
    if active_only:
        query += " WHERE active = 1"
    sql, params = dialect.render(query, params)
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]
