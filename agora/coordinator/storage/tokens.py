"""Token CRUD operations — backend-agnostic."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect

logger = logging.getLogger(__name__)


async def save_token(
    db: Any, dialect: Dialect,
    token_id: str, token_hash: str,
    principal_id: str, role: str,
    scopes: list[str] | None = None,
    tenant_id: str = "default",
    expires_at: str | None = None,
) -> dict:
    scopes_json = json.dumps(scopes or [])
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        """INSERT INTO tokens
        (token_id, token_hash, principal_id, role,
         scopes, tenant_id, expires_at, created_at,
         is_revoked, revoked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)""",
        [token_id, token_hash, principal_id, role,
         scopes_json, tenant_id, expires_at, now])
    await db.execute(sql, params)
    await db.commit()
    return {"token_id": token_id, "principal_id": principal_id,
            "role": role, "scopes": scopes or [],
            "tenant_id": tenant_id, "expires_at": expires_at,
            "created_at": now, "is_revoked": False}


async def get_token(
    db: Any, dialect: Dialect, token_id: str,
) -> Optional[dict]:
    sql, params = dialect.render(
        "SELECT * FROM tokens WHERE token_id = ?", [token_id])
    async with db.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    d = dict(row)
    if "scopes" in d and isinstance(d["scopes"], str):
        d["scopes"] = json.loads(d["scopes"])
    if "is_revoked" in d and isinstance(d["is_revoked"], int):
        d["is_revoked"] = bool(d["is_revoked"])
    return d


async def revoke_token(
    db: Any, dialect: Dialect, token_id: str,
) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        "UPDATE tokens SET is_revoked = 1, revoked_at = ? "
        "WHERE token_id = ? AND is_revoked = 0",
        [now, token_id])
    cursor = await db.execute(sql, params)
    await db.commit()
    return cursor.rowcount > 0


async def list_tokens(
    db: Any, dialect: Dialect,
    principal_id: str | None = None,
    include_revoked: bool = False,
) -> list[dict]:
    clauses: list[str] = []
    params: list = []
    if not include_revoked:
        clauses.append("is_revoked = 0")
    if principal_id is not None:
        clauses.append("principal_id = ?")
        params.append(principal_id)
    where = " AND ".join(clauses) if clauses else "1=1"
    sql, params = dialect.render(
        f"SELECT * FROM tokens WHERE {where} "
        "ORDER BY created_at DESC", params)
    async with db.execute(sql, params) as cursor:
        rows = await cursor.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if "scopes" in d and isinstance(d["scopes"], str):
            d["scopes"] = json.loads(d["scopes"])
        if "is_revoked" in d and isinstance(d["is_revoked"], int):
            d["is_revoked"] = bool(d["is_revoked"])
        result.append(d)
    return result
