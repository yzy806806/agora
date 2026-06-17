"""SQLite → Postgres migration logic.

Reads all rows from SQLite, applies type conversions,
writes to Postgres. Supports dry-run and idempotent operation.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from .migrate_converters import convert_boolean, convert_jsonb, convert_timestamp
from .schema_postgres import (
    BOOLEAN_COLUMNS,
    JSONB_COLUMNS,
    POSTGRES_TABLES,
    TIMESTAMP_COLUMNS,
)

logger = logging.getLogger(__name__)


def _convert_row(
    table: str, row: dict[str, Any],
) -> dict[str, Any]:
    """Apply type conversions for a single row."""
    jsonb_cols = set(JSONB_COLUMNS.get(table, []))
    bool_cols = set(BOOLEAN_COLUMNS.get(table, []))
    ts_cols = set(TIMESTAMP_COLUMNS.get(table, []))

    converted: dict[str, Any] = {}
    for col, val in row.items():
        if col in jsonb_cols:
            converted[col] = convert_jsonb(val)
        elif col in bool_cols:
            converted[col] = convert_boolean(val)
        elif col in ts_cols:
            converted[col] = convert_timestamp(val)
        else:
            converted[col] = val
    return converted


def read_sqlite_tables(db_path: str) -> dict[str, list[dict[str, Any]]]:
    """Read all tables from SQLite, returning {table: [rows]}."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        result: dict[str, list[dict[str, Any]]] = {}
        for table in POSTGRES_TABLES:
            try:
                rows = conn.execute(
                    f"SELECT * FROM {table}"  # noqa: S608
                ).fetchall()
                result[table] = [dict(r) for r in rows]
            except sqlite3.OperationalError:
                logger.info("Table %s not found in SQLite, skipping", table)
                result[table] = []
        return result
    finally:
        conn.close()


async def write_to_postgres(
    dsn: str,
    tables_data: dict[str, list[dict[str, Any]]],
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """Write converted rows to Postgres.

    Returns {table: rows_written}.
    Idempotent: skips tables that already have rows.
    """
    try:
        import asyncpg  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "asyncpg is required for Postgres migration. "
            "Install with: pip install asyncpg"
        ) from exc

    from .schema_postgres import PG_SCHEMA_SQL

    conn = await asyncpg.connect(dsn)
    counts: dict[str, int] = {}
    try:
        # Create schema
        if not dry_run:
            await conn.execute(PG_SCHEMA_SQL)

        for table in POSTGRES_TABLES:
            rows = tables_data.get(table, [])
            if not rows:
                counts[table] = 0
                continue

            # Idempotent: skip if table already has data
            existing = await conn.fetchval(
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608
            )
            if existing and existing > 0:
                logger.info(
                    "Table %s already has %d rows, skipping",
                    table, existing,
                )
                counts[table] = 0
                continue

            # Convert rows
            converted = [_convert_row(table, r) for r in rows]

            if dry_run:
                logger.info(
                    "[DRY RUN] Would insert %d rows into %s",
                    len(converted), table,
                )
                counts[table] = len(converted)
                continue

            if not converted:
                counts[table] = 0
                continue

            # Build INSERT
            cols = list(converted[0].keys())
            col_str = ", ".join(cols)
            placeholders = ", ".join(
                f"${i+1}" for i in range(len(cols))
            )
            sql = (
                f"INSERT INTO {table} ({col_str}) "  # noqa: S608
                f"VALUES ({placeholders})"
            )

            inserted = 0
            for row in converted:
                vals = [row.get(c) for c in cols]
                await conn.execute(sql, *vals)
                inserted += 1

            # Reset BIGSERIAL sequence
            await _reset_sequence(conn, table)

            counts[table] = inserted
            logger.info("Inserted %d rows into %s", inserted, table)

    finally:
        await conn.close()

    return counts


async def _reset_sequence(conn: Any, table: str) -> None:
    """Reset BIGSERIAL sequence to MAX(id) for a table."""
    # Only tables with BIGSERIAL PK need sequence reset
    serial_tables = {
        "messages", "votes", "assessments", "judgment_records",
        "bootstrap_triggers", "bootstrap_schedules",
        "bootstrap_approvals", "bootstrap_agents", "events",
        "rate_limit_usage", "execution_slots", "resource_locks",
        "roles", "tokens", "audit_log", "session_notes",
    }
    if table not in serial_tables:
        return
    seq_name = f"{table}_id_seq"
    try:
        await conn.execute(
            f"SELECT setval('{seq_name}', "  # noqa: S608
            f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
        )
    except Exception:
        logger.debug("Could not reset sequence %s", seq_name, exc_info=True)

