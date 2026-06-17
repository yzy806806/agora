"""RBAC storage: roles, tokens, audit_log — backend-agnostic."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect
from .schema import DEFAULT_ROLES

logger = logging.getLogger(__name__)


# --- Role CRUD ---

async def seed_default_roles(db: Any) -> None:
    """Insert default roles if not present."""
    now = datetime.now(timezone.utc).isoformat()
    for name, perms in DEFAULT_ROLES.items():
        await db.execute(
            "INSERT OR IGNORE INTO roles "
            "(name, permissions_json, created_at) VALUES (?, ?, ?)",
            [name, json.dumps(perms), now])
    await db.commit()
    logger.info("Seeded default RBAC roles")


async def get_role(db: Any, dialect: Dialect,
                   name: str) -> Optional[dict]:
    sql, params = dialect.render(
        "SELECT id, name, permissions_json, created_at "
        "FROM roles WHERE name = ?", [name])
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "id": row["id"], "name": row["name"],
        "permissions": json.loads(row["permissions_json"]),
        "created_at": row["created_at"],
    }


async def list_roles(db: Any, dialect: Dialect) -> list[dict]:
    sql, params = dialect.render(
        "SELECT id, name, permissions_json, created_at FROM roles", [])
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [
        {"id": r["id"], "name": r["name"],
         "permissions": json.loads(r["permissions_json"]),
         "created_at": r["created_at"]}
        for r in rows
    ]


# --- Token CRUD ---

async def create_token(
    db: Any, dialect: Dialect,
    principal_id: str, role: str, token_hash: str,
    token_id: str, scopes: list[str] | None = None,
    expires_at: Optional[str] = None, tenant_id: str = "default",
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    scopes_json = json.dumps(scopes or [])
    sql, params = dialect.render(
        "INSERT INTO tokens (token_id, token_hash, principal_id, role, "
        "scopes, tenant_id, expires_at, is_revoked, revoked_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, ?)",
        [token_id, token_hash, principal_id, role,
         scopes_json, tenant_id, expires_at, now])
    await db.execute(sql, params)
    await db.commit()
    return {"token_id": token_id, "principal_id": principal_id,
            "role": role, "scopes": scopes or [],
            "token_hash": token_hash, "expires_at": expires_at,
            "created_at": now, "tenant_id": tenant_id}


async def get_token_by_hash(
    db: Any, dialect: Dialect, token_hash: str,
) -> Optional[dict]:
    sql, params = dialect.render(
        "SELECT * FROM tokens WHERE token_hash = ? "
        "AND is_revoked = 0", [token_hash])
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    d = dict(row)
    if "scopes" in d and isinstance(d["scopes"], str):
        d["scopes"] = json.loads(d["scopes"])
    return d


async def revoke_token(db: Any, dialect: Dialect,
                       token_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        "UPDATE tokens SET is_revoked = 1, revoked_at = ? "
        "WHERE id = ?", [now, token_id])
    await db.execute(sql, params)
    await db.commit()


# --- Audit Log CRUD ---

async def log_audit(
    db: Any, dialect: Dialect,
    event_type: str, actor_id: str, action: str,
    resource: Optional[str] = None,
    actor_role: Optional[str] = None,
    details: Optional[dict] = None, tenant_id: str = "default",
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        "INSERT INTO audit_log (event_type, actor_id, actor_role, "
        "action, resource, details_json, timestamp, tenant_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [event_type, actor_id, actor_role, action, resource,
         json.dumps(details) if details else None, now, tenant_id])
    async with db.execute(sql, params) as cur:
        audit_id: int = cur.lastrowid
    await db.commit()
    return audit_id


async def query_audit(
    db: Any, dialect: Dialect,
    tenant_id: str = "default",
    actor_id: Optional[str] = None,
    event_type: Optional[str] = None, limit: int = 100,
) -> list[dict]:
    clauses = ["tenant_id = ?"]
    params: list = [tenant_id]
    if actor_id:
        clauses.append("actor_id = ?"); params.append(actor_id)
    if event_type:
        clauses.append("event_type = ?"); params.append(event_type)
    params.append(limit)
    where = " AND ".join(clauses)
    sql, params = dialect.render(
        f"SELECT id, event_type, actor_id, actor_role, action, "
        f"resource, details_json, timestamp, tenant_id "
        f"FROM audit_log WHERE {where} "
        f"ORDER BY timestamp DESC LIMIT ?", params)
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]
