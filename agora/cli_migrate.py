"""CLI tool for SQLite to Postgres migration.

Usage:
    agora migrate --from-sqlite /data/agora.db --to-postgres postgresql://...
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from agora.coordinator.storage.migrate_core import (
    read_sqlite_tables,
    write_to_postgres,
)

logger = logging.getLogger(__name__)


def add_migrate_parser(
    sub: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    """Add the 'migrate' subcommand to an argparse sub-parsers group."""
    sp = sub.add_parser(
        "migrate",
        help="Migrate data from SQLite to Postgres",
    )
    sp.add_argument(
        "--from-sqlite",
        required=True,
        help="Path to SQLite database file",
    )
    sp.add_argument(
        "--to-postgres",
        required=True,
        help="Postgres DSN, e.g. postgresql://user:pass@host/db",
    )
    sp.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview changes without writing to Postgres",
    )
    sp.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable verbose logging",
    )
    sp.set_defaults(func=_cmd_migrate)


async def _verify(pg_dsn: str, expected: dict) -> None:
    """Verify row counts in Postgres match source."""
    import asyncpg
    from agora.coordinator.storage.schema_postgres import POSTGRES_TABLES

    conn = await asyncpg.connect(pg_dsn)
    try:
        for table in POSTGRES_TABLES:
            actual = await conn.fetchval(
                f"SELECT COUNT(*) FROM {table}"
            )
            source = len(expected.get(table, []))
            if actual != source:
                logger.warning(
                    "VERIFY FAILED: %s has %d rows, expected %d",
                    table, actual, source,
                )
            else:
                logger.info("Verified %s: %d rows OK", table, actual)
    finally:
        await conn.close()


def _cmd_migrate(args: argparse.Namespace) -> None:
    """Execute the migrate command."""
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    sqlite_path = args.from_sqlite
    pg_dsn = args.to_postgres
    dry_run = args.dry_run

    logger.info("Reading from SQLite: %s", sqlite_path)
    tables_data = read_sqlite_tables(sqlite_path)
    total_rows = sum(len(rows) for rows in tables_data.values())
    logger.info(
        "Read %d total rows across %d tables",
        total_rows, len(tables_data),
    )

    if dry_run:
        logger.info("DRY RUN - no data will be written to Postgres")

    counts = asyncio.run(
        write_to_postgres(pg_dsn, tables_data, dry_run=dry_run)
    )

    # Print summary
    print("\nMigration summary:")
    print("-" * 40)
    for table, count in counts.items():
        status = "skipped" if count == 0 else f"{count} rows"
        print(f"  {table}: {status}")

    written = sum(counts.values())
    print(f"\nTotal: {written} rows "
          f"{'would be ' if dry_run else ''}written")

    if not dry_run and written > 0:
        logger.info("Verifying row counts...")
        asyncio.run(_verify(pg_dsn, tables_data))
