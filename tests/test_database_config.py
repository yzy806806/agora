"""Tests for DatabaseConfig and Settings database section."""
import os
from unittest.mock import patch

import pytest

from agora.coordinator.config import DatabaseConfig, Settings


class TestDatabaseConfig:
    def test_defaults(self):
        cfg = DatabaseConfig()
        assert cfg.backend == "sqlite"
        assert cfg.pool_min_size == 2
        assert cfg.pool_max_size == 20
        assert cfg.pool_acquire_timeout == 30
        assert cfg.database_url == ""

    def test_resolved_backend_default(self):
        cfg = DatabaseConfig()
        with patch.dict(os.environ, {}, clear=True):
            assert cfg.resolved_backend() == "sqlite"

    def test_resolved_backend_env_url_forces_postgres(self):
        cfg = DatabaseConfig()
        with patch.dict(os.environ, {"AGORA_DATABASE_URL": "pg://x"}):
            assert cfg.resolved_backend() == "postgres"

    def test_resolved_url_env_override(self):
        cfg = DatabaseConfig(database_url="pg://config")
        with patch.dict(os.environ, {"AGORA_DATABASE_URL": "pg://env"}):
            assert cfg.resolved_url() == "pg://env"

    def test_resolved_url_from_config(self):
        cfg = DatabaseConfig(database_url="pg://config")
        with patch.dict(os.environ, {}, clear=True):
            assert cfg.resolved_url() == "pg://config"

    def test_resolved_url_empty_when_no_env_no_config(self):
        cfg = DatabaseConfig()
        with patch.dict(os.environ, {}, clear=True):
            assert cfg.resolved_url() == ""

    def test_explicit_postgres_backend(self):
        cfg = DatabaseConfig(
            backend="postgres", database_url="pg://host/db"
        )
        with patch.dict(os.environ, {}, clear=True):
            assert cfg.resolved_backend() == "postgres"
            assert cfg.resolved_url() == "pg://host/db"


class TestSettingsDatabaseSection:
    def test_settings_has_database(self):
        s = Settings()
        assert isinstance(s.database, DatabaseConfig)

    def test_database_default_backend(self):
        s = Settings()
        assert s.database.backend == "sqlite"

    def test_get_db_path_delegates_to_database(self):
        s = Settings(db_path="")
        assert s.get_db_path() == s.database.db_path

    def test_get_db_path_explicit_overrides(self):
        s = Settings(db_path="/custom/path.db")
        assert s.get_db_path() == "/custom/path.db"

    def test_env_database_url_forces_postgres(self):
        """AGORA_DATABASE_URL env var forces postgres backend."""
        with patch.dict(
            os.environ, {"AGORA_DATABASE_URL": "postgresql://u@h/db"}
        ):
            cfg = DatabaseConfig()
            assert cfg.resolved_backend() == "postgres"
            assert cfg.resolved_url() == "postgresql://u@h/db"
