"""Tests for schema_postgres.py: DDL validity and metadata consistency."""

from __future__ import annotations

import re

from agora.coordinator.storage.schema_postgres import (
    BOOLEAN_COLUMNS,
    JSONB_COLUMNS,
    PG_SCHEMA_SQL,
    POSTGRES_TABLES,
    TIMESTAMP_COLUMNS,
)


class TestPostgresSchemaDDL:
    """Verify DDL string is well-formed."""

    def test_schema_not_empty(self) -> None:
        assert len(PG_SCHEMA_SQL) > 100

    def test_all_tables_in_ddl(self) -> None:
        """Every table in POSTGRES_TABLES must appear in DDL."""
        for table in POSTGRES_TABLES:
            pattern = rf"CREATE TABLE IF NOT EXISTS {table}\s*\("
            assert re.search(
                pattern, PG_SCHEMA_SQL,
            ), f"Table {table} missing from DDL"

    def test_no_sqlite_types(self) -> None:
        """DDL must not contain SQLite-specific types."""
        sqlite_types = [
            "INTEGER PRIMARY KEY AUTOINCREMENT",
            "PRAGMA",
        ]
        for st in sqlite_types:
            assert st not in PG_SCHEMA_SQL, (
                f"Found SQLite-specific: {st}"
            )

    def test_uses_postgres_types(self) -> None:
        """DDL must use Postgres-specific types."""
        assert "TIMESTAMPTZ" in PG_SCHEMA_SQL
        assert "JSONB" in PG_SCHEMA_SQL
        assert "BOOLEAN" in PG_SCHEMA_SQL
        assert "BIGSERIAL" in PG_SCHEMA_SQL

    def test_gin_indexes_present(self) -> None:
        """GIN indexes for JSONB queryable columns."""
        assert "USING GIN" in PG_SCHEMA_SQL
        assert "idx_agents_capabilities_gin" in PG_SCHEMA_SQL
        assert "idx_tasks_required_caps_gin" in PG_SCHEMA_SQL
        assert "idx_tasks_depends_on_gin" in PG_SCHEMA_SQL

    def test_bytea_for_blob(self) -> None:
        """project_artifacts.value should use BYTEA."""
        assert "BYTEA" in PG_SCHEMA_SQL

    def test_foreign_keys_use_references(self) -> None:
        """Postgres uses REFERENCES instead of FOREIGN KEY inline."""
        assert "REFERENCES" in PG_SCHEMA_SQL


class TestPostgresTableList:
    """Verify POSTGRES_TABLES matches DDL."""

    def test_table_count(self) -> None:
        assert len(POSTGRES_TABLES) == 28

    def test_no_duplicates(self) -> None:
        assert len(POSTGRES_TABLES) == len(set(POSTGRES_TABLES))

    def test_key_tables_present(self) -> None:
        key = [
            "agents", "motions", "messages", "votes",
            "tasks", "roles", "tokens", "audit_log",
            "pipeline_runs", "notifications", "file_nodes",
        ]
        for t in key:
            assert t in POSTGRES_TABLES


class TestMetadataConsistency:
    """Verify JSONB/BOOLEAN/TIMESTAMP column maps reference valid tables."""

    def test_jsonb_tables_exist(self) -> None:
        for table in JSONB_COLUMNS:
            assert table in POSTGRES_TABLES, (
                f"JSONB_COLUMNS references unknown table: {table}"
            )

    def test_boolean_tables_exist(self) -> None:
        for table in BOOLEAN_COLUMNS:
            assert table in POSTGRES_TABLES, (
                f"BOOLEAN_COLUMNS references unknown table: {table}"
            )

    def test_timestamp_tables_exist(self) -> None:
        for table in TIMESTAMP_COLUMNS:
            assert table in POSTGRES_TABLES, (
                f"TIMESTAMP_COLUMNS references unknown table: {table}"
            )

    def test_jsonb_cols_in_ddl(self) -> None:
        """JSONB columns should appear as JSONB in DDL."""
        for table, cols in JSONB_COLUMNS.items():
            for col in cols:
                # Find the column in the table definition
                # Just verify column name appears in DDL
                assert col in PG_SCHEMA_SQL, (
                    f"JSONB col {table}.{col} not in DDL"
                )
