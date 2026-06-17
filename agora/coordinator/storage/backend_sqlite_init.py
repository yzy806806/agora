"""SQLite backend initialization: schema + migrations.

Extracted from storage.py init_db() to keep backend_sqlite.py under 80 lines.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import aiosqlite

from . import rbac as _rbac
from .backend_sqlite_migrations import run_migrations
from .schema import SCHEMA_SQL, SCHEMA_VERSION

if TYPE_CHECKING:
    from .backend_sqlite import SqliteBackend

logger = logging.getLogger(__name__)


async def init_sqlite_db(backend: "SqliteBackend") -> None:
    """Initialize database tables and run pending migrations."""
    async with aiosqlite.connect(backend.db_path) as db:
        await db.executescript(SCHEMA_SQL)
        await db.execute(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT)",
        )
        async with db.execute(
            "SELECT MAX(version) FROM schema_version"
        ) as cur:
            row = await cur.fetchone()
        current_ver = row[0] if row and row[0] else SCHEMA_VERSION

        current_ver = await run_migrations(db, current_ver)

        await db.execute(
            "INSERT OR IGNORE INTO schema_version VALUES (?, ?)",
            [SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()],
        )
        await db.commit()

        # Seed default RBAC roles if roles table is empty
        async with db.execute("SELECT COUNT(*) FROM roles") as cur:
            row = await cur.fetchone()
        if row and row[0] == 0:
            await _rbac.seed_default_roles(db)
    logger.info("Database initialized at %s", backend.db_path)
