"""Agent CRUD operations — backend-agnostic.

All functions take a connection object and a Dialect instance
instead of an aiosqlite.Connection directly.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect

logger = logging.getLogger(__name__)


def _normalize_agent(d: dict) -> dict:
    """Normalize agent dict from DB row."""
    if "is_approved" in d and isinstance(d["is_approved"], int):
        d["is_approved"] = bool(d["is_approved"])
    for key in ("capabilities", "active_tasks", "allowed_discussion_roles"):
        if key in d and isinstance(d[key], str):
            d[key] = json.loads(d[key])
    return d


async def register_agent(
    db: Any, dialect: Dialect,
    agent_id: str, name: str, model: str = "unknown",
    capabilities: list[str] | None = None,
    role: str = "participant", agent_type: str = "hermes",
    max_concurrent_tasks: int = 2, agent_token: str = "",
    is_approved: bool = False, approval_status: str = "pending",
    tpm_limit: int = 10000, tpm_burst_factor: float = 1.5,
    registration_token: str = "",
    matrix_user_id: str = "",
) -> dict:
    caps_json = json.dumps(capabilities or [])
    active_tasks_json = json.dumps([])
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        """INSERT INTO agents
           (agent_id, name, model, capabilities, role,
            agent_type, max_concurrent_tasks, agent_token,
            is_approved, approval_status, load, active_tasks,
            registered_at, is_online, tpm_limit, tpm_burst_factor,
            registration_token, matrix_user_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [agent_id, name, model, caps_json, role,
         agent_type, max_concurrent_tasks, agent_token,
         1 if is_approved else 0, approval_status, 0.0,
         active_tasks_json, now, 1, tpm_limit, tpm_burst_factor,
         registration_token, matrix_user_id],
    )
    await db.execute(sql, params)
    await db.commit()
    return {
        "agent_id": agent_id, "name": name, "model": model,
        "capabilities": capabilities or [], "role": role,
        "agent_type": agent_type,
        "max_concurrent_tasks": max_concurrent_tasks,
        "agent_token": agent_token,
        "is_approved": is_approved,
        "approval_status": approval_status,
        "load": 0.0, "active_tasks": [],
        "registered_at": now, "is_online": True,
        "last_seen": None,
        "tpm_limit": tpm_limit,
        "tpm_burst_factor": tpm_burst_factor,
        "registration_token": registration_token,
        "matrix_user_id": matrix_user_id,
    }


async def get_agent(db: Any, dialect: Dialect, agent_id: str
                    ) -> Optional[dict]:
    sql, params = dialect.render(
        "SELECT * FROM agents WHERE agent_id = ?", [agent_id])
    async with db.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    return _normalize_agent(dict(row))


async def find_agent_by_name(db: Any, dialect: Dialect, name: str
                             ) -> Optional[dict]:
    """Find an agent by name (for idempotent re-registration)."""
    sql, params = dialect.render(
        "SELECT * FROM agents WHERE name = ? ORDER BY registered_at DESC LIMIT 1", [name])
    async with db.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    return _normalize_agent(dict(row))


async def get_agent_by_token(db: Any, dialect: Dialect, token: str
                             ) -> Optional[dict]:
    sql, params = dialect.render(
        "SELECT * FROM agents WHERE agent_token = ?", [token])
    async with db.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    return _normalize_agent(dict(row))


async def get_agent_by_registration_token(
    db: Any, dialect: Dialect, token: str,
) -> Optional[dict]:
    """Look up agent by registration_token (Phase 15.C)."""
    sql, params = dialect.render(
        "SELECT * FROM agents WHERE registration_token = ?", [token])
    async with db.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    return _normalize_agent(dict(row))


async def list_agents(db: Any, dialect: Dialect,
                      online_only: bool = False) -> list[dict]:
    query = "SELECT * FROM agents"
    params: list = []
    if online_only:
        query += " WHERE is_online = 1"
    sql, params = dialect.render(query, params)
    async with db.execute(sql, params) as cursor:
        rows = [dict(row) async for row in cursor]
    return [_normalize_agent(d) for d in rows]


async def set_agent_online(db: Any, dialect: Dialect,
                           agent_id: str, online: bool) -> None:
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        "UPDATE agents SET is_online = ?, last_seen_at = ? WHERE agent_id = ?",
        [1 if online else 0, now, agent_id])
    await db.execute(sql, params)
    await db.commit()


async def deregister_agent(db: Any, dialect: Dialect,
                           agent_id: str) -> None:
    sql1, p1 = dialect.render(
        "DELETE FROM rate_limit_usage WHERE agent_id = ?", [agent_id])
    sql2, p2 = dialect.render(
        "DELETE FROM agents WHERE agent_id = ?", [agent_id])
    await db.execute(sql1, p1)
    await db.execute(sql2, p2)
    await db.commit()


async def set_agent_approval(db: Any, dialect: Dialect,
                             agent_id: str, is_approved: bool,
                             approval_status: str) -> None:
    # Phase 15.C fix: do NOT clear registration_token here.
    # Token is cleared only after agent successfully retrieves agent_token
    # via GET /agents/register/{id}/status (one-time read pattern).
    sql, params = dialect.render(
        """UPDATE agents SET is_approved = ?, approval_status = ?
           WHERE agent_id = ?""",
        [1 if is_approved else 0, approval_status, agent_id])
    await db.execute(sql, params)
    await db.commit()


async def clear_registration_token(
    db: Any, dialect: Dialect, agent_id: str,
) -> None:
    """Clear registration_token after one-time agent_token retrieval."""
    sql, params = dialect.render(
        "UPDATE agents SET registration_token = '' WHERE agent_id = ?",
        [agent_id],
    )
    await db.execute(sql, params)
    await db.commit()


async def update_agent_tpm_config(
    db: Any, dialect: Dialect, agent_id: str,
    tpm_limit: int | None = None,
    tpm_burst_factor: float | None = None,
) -> None:
    parts, params = [], []
    if tpm_limit is not None:
        parts.append("tpm_limit = ?"); params.append(tpm_limit)
    if tpm_burst_factor is not None:
        parts.append("tpm_burst_factor = ?"); params.append(tpm_burst_factor)
    if not parts:
        return
    params.append(agent_id)
    sql, params = dialect.render(
        f"UPDATE agents SET {', '.join(parts)} WHERE agent_id = ?", params)
    await db.execute(sql, params)
    await db.commit()


async def update_agent_config(
    db: Any, dialect: Dialect, agent_id: str, *,
    tpm_limit: int | None = None,
    tpm_burst_factor: float | None = None,
    max_concurrent_tasks: int | None = None,
    role: str | None = None,
    allowed_discussion_roles: list[str] | None = None,
    matrix_user_id: str | None = None,
) -> None:
    parts, params = [], []
    if tpm_limit is not None:
        parts.append("tpm_limit = ?"); params.append(tpm_limit)
    if tpm_burst_factor is not None:
        parts.append("tpm_burst_factor = ?"); params.append(tpm_burst_factor)
    if max_concurrent_tasks is not None:
        parts.append("max_concurrent_tasks = ?"); params.append(max_concurrent_tasks)
    if role is not None:
        parts.append("role = ?"); params.append(role)
    if allowed_discussion_roles is not None:
        parts.append("allowed_discussion_roles = ?")
        params.append(json.dumps(allowed_discussion_roles))
    if matrix_user_id is not None:
        parts.append("matrix_user_id = ?"); params.append(matrix_user_id)
    if not parts:
        return
    params.append(agent_id)
    sql, params = dialect.render(
        f"UPDATE agents SET {', '.join(parts)} WHERE agent_id = ?", params)
    await db.execute(sql, params)
    await db.commit()
