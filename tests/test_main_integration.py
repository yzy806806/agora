"""Tests for heartbeat/timeout integration in main.py lifespan."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agora.coordinator.config import Settings
from agora.coordinator.timeout import TimeoutConfig


class TestConfigSettings:
    """Verify new heartbeat/timeout settings exist with defaults."""

    def test_heartbeat_defaults(self):
        s = Settings()
        assert s.heartbeat_interval_seconds == 30
        assert s.heartbeat_timeout_seconds == 120
        assert s.heartbeat_max_missed == 3

    def test_timeout_defaults(self):
        s = Settings()
        assert s.round_timeout_seconds == 300
        assert s.vote_timeout_seconds == 120
        assert s.discussion_timeout_seconds == 1800

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("AGORA_HEARTBEAT_INTERVAL_SECONDS", "15")
        monkeypatch.setenv("AGORA_ROUND_TIMEOUT_SECONDS", "600")
        s = Settings()
        assert s.heartbeat_interval_seconds == 15
        assert s.round_timeout_seconds == 600


class TestTimeoutConfigFromSettings:
    """Verify TimeoutConfig is built correctly from Settings."""

    def test_timeout_config_values(self):
        s = Settings()
        cfg = TimeoutConfig(
            round_timeout=s.round_timeout_seconds,
            vote_timeout=s.vote_timeout_seconds,
            discussion_timeout=s.discussion_timeout_seconds,
        )
        assert cfg.round_timeout == 300
        assert cfg.vote_timeout == 120
        assert cfg.discussion_timeout == 1800


class TestLifespanIntegration:
    """Test that lifespan initializes heartbeat and timeout managers."""

    @pytest.mark.asyncio
    async def test_lifespan_creates_managers(self):
        from agora.coordinator.main import lifespan

        app_mock = MagicMock()
        app_mock.state = MagicMock()

        with patch("agora.coordinator.main.Storage") as StorageMock, \
             patch("agora.coordinator.main.StorageManager") as SMMock, \
             patch("agora.coordinator.main.TenantManager"), \
             patch("agora.coordinator.main.init_tenant_deps"), \
             patch("agora.coordinator.main.StateMachine"), \
             patch("agora.coordinator.main.init_deps"), \
             patch("agora.coordinator.main.BootstrapEngine") as BEMock, \
             patch("agora.coordinator.main.HeartbeatManager") as HBMok, \
             patch("agora.coordinator.main.TimeoutManager") as TMMok:
            StorageMock.return_value = AsyncMock()
            StorageMock.return_value.init_db = AsyncMock()
            SMMock.return_value = AsyncMock()
            SMMock.return_value.init = AsyncMock()
            BEMock.return_value.init_routes = MagicMock()
            HBMok.return_value.start_heartbeat = AsyncMock()
            HBMok.return_value.stop = AsyncMock()

            async with lifespan(app_mock):
                HBMok.return_value.start_heartbeat.assert_awaited_once()
                TMMok.assert_called_once()
                assert app_mock.state.heartbeat_mgr is not None
                assert app_mock.state.timeout_mgr is not None

            HBMok.return_value.stop.assert_awaited_once()
