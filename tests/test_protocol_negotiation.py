"""Tests for Phase 14+.E.2: WELCOME message + protocol negotiation."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agora.coordinator.models import MessageType
from agora.coordinator.protocol import (
    DEFAULT_VERSION,
    SUPPORTED_VERSIONS,
    build_welcome,
    negotiate_version,
    parse_version,
)
from agora.coordinator.ws import ConnectionHub


# ---------------------------------------------------------------------------
# protocol.py unit tests
# ---------------------------------------------------------------------------

class TestBuildWelcome:
    def test_contains_protocol_version(self):
        msg = build_welcome("agent-1")
        assert msg["type"] == MessageType.WELCOME
        assert msg["protocol_version"] == DEFAULT_VERSION
        assert "session_id" in msg
        assert msg["session_id"].startswith("sess-")

    def test_custom_max_version(self):
        msg = build_welcome("a1", max_protocol_version=1.0)
        assert msg["protocol_version"] == 1.0

    def test_server_capabilities_present(self):
        msg = build_welcome("a1")
        caps = msg["server_capabilities"]
        assert caps["discussion"] is True
        assert caps["task_execution"] is True

    def test_custom_session_token(self):
        msg = build_welcome("a1", session_token="my-token")
        assert msg["session_id"] == "my-token"

    def test_tenant_id_included(self):
        msg = build_welcome("a1", tenant_id="acme")
        assert msg["tenant_id"] == "acme"


class TestNegotiateVersion:
    def test_client_lower_than_server(self):
        assert negotiate_version(1.0, 2.0) == 1.0

    def test_client_equal_to_server(self):
        assert negotiate_version(2.0, 2.0) == 2.0

    def test_client_higher_than_server(self):
        # Should snap to server max
        assert negotiate_version(3.0, 2.0) == 2.0

    def test_invalid_version_falls_back(self):
        assert negotiate_version(0.0, 2.0) == 1.0

    def test_negative_version_falls_back(self):
        assert negotiate_version(-1.0, 2.0) == 1.0

    def test_version_snaps_to_known(self):
        # 1.5 is not a known version, should snap to 2.0
        assert negotiate_version(1.5, 2.0) == 2.0


class TestParseVersion:
    def test_int_input(self):
        assert parse_version(2) == 2.0

    def test_float_input(self):
        assert parse_version(1.0) == 1.0

    def test_string_input(self):
        assert parse_version("2.0") == 2.0

    def test_invalid_string(self):
        assert parse_version("abc") == 0.0

    def test_none_input(self):
        assert parse_version(None) == 0.0

    def test_list_input(self):
        assert parse_version([1, 2]) == 0.0


# ---------------------------------------------------------------------------
# ConnectionHub protocol version storage tests
# ---------------------------------------------------------------------------

class TestConnectionHubProtocolVersion:
    def test_default_version_is_v1(self):
        hub = ConnectionHub()
        # Not connected, should default to 1.0
        assert hub.get_protocol_version("unknown") == 1.0

    def test_set_and_get_version(self):
        hub = ConnectionHub()
        hub.set_protocol_version("a1", 2.0)
        assert hub.get_protocol_version("a1") == 2.0

    def test_disconnect_clears_version(self):
        hub = ConnectionHub()
        hub._protocol_versions["a1"] = 2.0
        hub.disconnect("a1")
        assert hub.get_protocol_version("a1") == 1.0


# ---------------------------------------------------------------------------
# Integration: _handle_capabilities in ws_endpoint
# ---------------------------------------------------------------------------

class TestCapabilitiesHandler:
    @pytest.mark.asyncio
    async def test_v2_negotiation(self):
        from agora.coordinator.ws_endpoint import _handle_capabilities
        hub = ConnectionHub()
        hub.send = AsyncMock(return_value=True)
        storage = AsyncMock()
        storage.update_agent_capabilities = AsyncMock()
        storage.update_agent_model = AsyncMock()

        with patch(
            "agora.coordinator.config.settings"
        ) as mock_settings:
            mock_settings.protocol_version = 2.0
            await _handle_capabilities(
                "a1",
                {"protocol_version": 2.0, "name": "test", "model": "gpt-4"},
                storage, hub,
            )

        assert hub.get_protocol_version("a1") == 2.0
        hub.send.assert_called_once()
        resp = hub.send.call_args[0][1]
        assert resp["type"] == MessageType.WELCOME
        assert resp["payload"]["protocol_version"] == 2.0

    @pytest.mark.asyncio
    async def test_v1_fallback(self):
        from agora.coordinator.ws_endpoint import _handle_capabilities
        hub = ConnectionHub()
        hub.send = AsyncMock(return_value=True)
        storage = AsyncMock()
        storage.update_agent_capabilities = AsyncMock()
        storage.update_agent_model = AsyncMock()

        with patch(
            "agora.coordinator.config.settings"
        ) as mock_settings:
            mock_settings.protocol_version = 2.0
            await _handle_capabilities(
                "a1",
                {"protocol_version": 1.0},
                storage, hub,
            )

        assert hub.get_protocol_version("a1") == 1.0

    @pytest.mark.asyncio
    async def test_no_version_defaults_v1(self):
        from agora.coordinator.ws_endpoint import _handle_capabilities
        hub = ConnectionHub()
        hub.send = AsyncMock(return_value=True)
        storage = AsyncMock()
        storage.update_agent_capabilities = AsyncMock()
        storage.update_agent_model = AsyncMock()

        with patch(
            "agora.coordinator.config.settings"
        ) as mock_settings:
            mock_settings.protocol_version = 2.0
            # No protocol_version in payload → defaults to 1.0
            await _handle_capabilities("a1", {}, storage, hub)

        assert hub.get_protocol_version("a1") == 1.0
