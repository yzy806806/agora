"""Global storage for tenant registry — backend-agnostic.

Manages the global.db that stores the list of all tenants.
Each tenant's actual data lives in its own per-tenant agora.db.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from .dialect import Dialect

logger = logging.getLogger(__name__)

GLOBAL_SCHEMA_SQL = """\
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_tenants_active ON tenants(is_active);
"""


class GlobalStorage:
    """Manages the global.db tenant registry."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.dialect: Dialect = Dialect("sqlite")

    async def init_db(self) -> None:
        """Create global.db and tenants table if not exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.executescript(GLOBAL_SCHEMA_SQL)
            await db.commit()
        logger.info("Global DB initialized at %s", self.db_path)

    async def _connect(self):
        """Open a new connection with row_factory set."""
        db = await aiosqlite.connect(str(self.db_path))
        db.row_factory = aiosqlite.Row
        return db

    async def create_tenant(
        self, tenant_id: str, name: str, config: dict,
    ) -> dict:
        """Insert a new tenant row into global.db."""
        now = datetime.now(timezone.utc).isoformat()
        sql, params = self.dialect.render(
            "INSERT INTO tenants VALUES (?, ?, ?, ?, 1)",
            [tenant_id, name, json.dumps(config), now])
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.execute(sql, params)
            await db.commit()
        return {"tenant_id": tenant_id, "name": name,
                "config": config, "created_at": now, "is_active": 1}

    async def get_tenant(self, tenant_id: str) -> Optional[dict]:
        """Get a single tenant by ID."""
        sql, params = self.dialect.render(
            "SELECT * FROM tenants "
            "WHERE tenant_id = ? AND is_active = 1",
            [tenant_id])
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, params)
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    async def list_tenants(self) -> list[dict]:
        """List all active tenants."""
        sql, params = self.dialect.render(
            "SELECT * FROM tenants WHERE is_active = 1", [])
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, params)
            rows = await cursor.fetchall()
        return [self._row_to_dict(r) for r in rows]

    async def delete_tenant(self, tenant_id: str) -> bool:
        """Soft-delete a tenant (set is_active=0)."""
        sql, params = self.dialect.render(
            "UPDATE tenants SET is_active = 0 "
            "WHERE tenant_id = ?", [tenant_id])
        async with aiosqlite.connect(str(self.db_path)) as db:
            cursor = await db.execute(sql, params)
            await db.commit()
            return cursor.rowcount > 0

    @staticmethod
    def _row_to_dict(row: Any) -> dict:
        d = dict(row)
        if "config" in d and isinstance(d["config"], str):
            d["config"] = json.loads(d["config"])
        return d
