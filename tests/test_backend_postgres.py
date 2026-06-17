"""Tests for PostgresBackend and related modules.

Uses mocking for asyncpg Pool since no Postgres server is
available in CI. Tests validate:
- ABC contract enforcement
- Dialect property
- Pool lazy creation
- Query method delegation
- Schema DDL content
- Helper functions
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agora.coordinator.storage.backend import StorageBackend
from agora.coordinator.storage.backend_postgres import PostgresBackend
from agora.coordinator.storage.backend_postgres_helpers import (
    record_to_dict,
    records_to_dicts,
)


# --- StorageBackend ABC tests ---


class TestStorageBackendABC:
    """Verify the ABC cannot be instantiated directly."""

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError, match="abstract method"):
            StorageBackend()

    def test_required_abstract_methods(self):
        expected = {
            "dialect", "connection", "initialize",
            "execute", "execute_many",
            "fetch_one", "fetch_all", "fetch_val",
            "begin", "commit", "rollback",
            "acquire_lock", "release_lock",
        }
        actual = set(StorageBackend.__abstractmethods__)
        assert actual == expected


# --- PostgresBackend construction + dialect ---


class TestPostgresBackendConstruction:
    """Test construction and dialect property."""

    def test_dialect_is_postgres(self):
        backend = PostgresBackend("postgresql://user:***@localhost/db")
        assert backend.dialect.name == "postgres"

    def test_default_pool_config(self):
        backend = PostgresBackend("postgresql://u:***@h/d")
        assert backend._pool_min == 2
        assert backend._pool_max == 20
        assert backend._acquire_timeout == 30

    def test_custom_pool_config(self):
        backend = PostgresBackend(
            "postgresql://u:***@h/d",
            pool_min_size=5, pool_max_size=50,
            pool_acquire_timeout=60,
        )
        assert backend._pool_min == 5
        assert backend._pool_max == 50
        assert backend._acquire_timeout == 60

    def test_pool_initially_none(self):
        backend = PostgresBackend("postgresql://u:***@h/d")
        assert backend._pool is None
