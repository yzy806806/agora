"""Tests for PostgresBackend helpers and schema content."""

from __future__ import annotations

from agora.coordinator.storage.backend_postgres_helpers import (
    record_to_dict,
    records_to_dicts,
)
from agora.coordinator.storage.schema_postgres import PG_SCHEMA_SQL
from agora.coordinator.storage.schema_postgres_indexes import PG_INDEXES_SQL


class TestRecordHelpers:
    def test_record_to_dict_with_none(self):
        assert record_to_dict(None) == {}

    def test_record_to_dict_with_dict(self):
        assert record_to_dict({"a": 1}) == {"a": 1}

    def test_records_to_dicts(self):
        data = [{"a": 1}, {"b": 2}]
        assert records_to_dicts(data) == [{"a": 1}, {"b": 2}]

    def test_records_to_dicts_empty(self):
        assert records_to_dicts([]) == []


class TestSchemaContent:
    """Validate PG DDL has expected tables and types."""

    def test_schema_has_agents_table(self):
        assert "CREATE TABLE IF NOT EXISTS agents" in PG_SCHEMA_SQL

    def test_schema_has_timestamptz(self):
        assert "TIMESTAMPTZ" in PG_SCHEMA_SQL

    def test_schema_has_jsonb(self):
        assert "JSONB" in PG_SCHEMA_SQL

    def test_schema_has_boolean(self):
        assert "BOOLEAN" in PG_SCHEMA_SQL

    def test_schema_has_bigserial(self):
        assert "BIGSERIAL" in PG_SCHEMA_SQL

    def test_schema_has_bytea(self):
        assert "BYTEA" in PG_SCHEMA_SQL

    def test_schema_has_all_major_tables(self):
        tables = [
            "agents", "motions", "messages", "votes",
            "assessments", "judgment_records",
            "bootstrap_triggers", "bootstrap_schedules",
            "bootstrap_approvals", "bootstrap_agents",
            "events", "task_graphs", "tasks",
            "rate_limit_usage", "execution_slots",
            "resource_locks", "roles", "tokens",
            "audit_log", "session_records", "session_notes",
            "project_artifacts", "pipeline_runs",
            "notifications", "file_nodes", "file_locks",
        ]
        for t in tables:
            assert f"CREATE TABLE IF NOT EXISTS {t}" in PG_SCHEMA_SQL, (
                f"Missing table: {t}"
            )


class TestIndexesContent:
    """Validate PG indexes include GIN indexes."""

    def test_has_gin_indexes(self):
        assert "USING GIN" in PG_INDEXES_SQL

    def test_has_agents_capabilities_gin(self):
        assert "idx_agents_capabilities_gin" in PG_INDEXES_SQL

    def test_has_tasks_required_caps_gin(self):
        assert "idx_tasks_required_caps_gin" in PG_INDEXES_SQL
