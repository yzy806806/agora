"""SQLite migration runner – extracted for line-count constraint."""
from __future__ import annotations

import logging

import aiosqlite

from .schema import (
    MIGRATION_10_TO_11, MIGRATION_11_TO_12, MIGRATION_12_TO_13,
    MIGRATION_12_TO_13_PIPELINES, MIGRATION_14_TO_15,
    MIGRATION_15_TO_16, MIGRATION_16_TO_17, MIGRATION_17_TO_18,
    MIGRATION_18_TO_19, MIGRATION_19_TO_20, MIGRATION_20_TO_21,
    MIGRATION_21_TO_22, MIGRATION_6_TO_7, MIGRATION_7_TO_8,
    MIGRATION_8_TO_9, MIGRATION_9_TO_10, SCHEMA_VERSION,
)

logger = logging.getLogger(__name__)

_DUP_COL_MSG = "duplicate column name"


async def _column_exists(
    db: aiosqlite.Connection, table: str, column: str,
) -> bool:
    """Check whether *column* exists in *table* (SQLite pragma)."""
    async with db.execute(
        f"PRAGMA table_info({table})"
    ) as cur:
        rows = await cur.fetchall()
    return any(row[1] == column for row in rows)


async def run_migrations(
    db: aiosqlite.Connection, current_ver: int,
) -> int:
    """Run pending schema migrations. Returns new version."""
    migrations = [
        (7, MIGRATION_6_TO_7, "Phase 9.3 agent columns"),
        (8, MIGRATION_7_TO_8, "Phase 9.4 rate_limit_usage"),
        (9, MIGRATION_8_TO_9, "Phase 10 parallel + RBAC"),
        (10, MIGRATION_9_TO_10, "Phase 11.1b agent config"),
        (11, MIGRATION_10_TO_11, "Phase 12.5a session_records"),
        (12, MIGRATION_11_TO_12, "Phase 13 pipeline_runs"),
        (13, MIGRATION_12_TO_13, "Phase 13 notifications"),
        (14, MIGRATION_12_TO_13_PIPELINES, "Phase 13b failed_phase"),
        (15, MIGRATION_14_TO_15, "Phase 14 workspace tables"),
        (16, MIGRATION_15_TO_16, "Phase 14.5b workspace_paths"),
        (17, MIGRATION_16_TO_17, "Phase 14+ Part D webhooks"),
        (18, MIGRATION_17_TO_18, "Phase 14+.E.3 task_result column"),
        (19, MIGRATION_18_TO_19, "Phase 15.C registration_token column"),
        (20, MIGRATION_19_TO_20, "Phase 16.4 MCP sessions table"),
        (21, MIGRATION_20_TO_21, "Phase 17 contact_url column"),
        (22, MIGRATION_21_TO_22, "Phase 18 nullable motion_id"),
    ]
    for target_ver, stmts, label in migrations:
        if current_ver < target_ver:
            for stmt in stmts:
                stmt_upper = stmt.strip().upper()
                if stmt_upper.startswith("ALTER TABLE") and "ADD COLUMN" in stmt_upper:
                    # Extract table and column name to guard dupes
                    parts = stmt.split()
                    try:
                        tbl_idx = parts.index("TABLE") + 1
                        col_idx = parts.index("COLUMN") + 1
                        tbl = parts[tbl_idx]
                        col = parts[col_idx]
                    except (ValueError, IndexError):
                        tbl, col = "", ""
                    if tbl and col and await _column_exists(db, tbl, col):
                        logger.debug(
                            "Skip migration: %s.%s already exists",
                            tbl, col,
                        )
                        continue
                try:
                    await db.execute(stmt)
                except Exception as exc:
                    if _DUP_COL_MSG in str(exc).lower():
                        logger.debug("Skip dup-column migration: %s", stmt)
                    else:
                        raise
            logger.info(
                "Applied migration %d→%d (%s)",
                target_ver - 1, target_ver, label,
            )
            current_ver = target_ver
    return current_ver
