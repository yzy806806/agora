"""Tests for MCP Server base framework (Phase 16.1).

Covers:
- MCP app creation and mounting
- Auth middleware: whitelist, token validation, 401 responses
- Deps injection
- Session mapping
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agora.coordinator.mcp.server import mcp_server, create_mcp_app
from agora.coordinator.mcp.deps import (
    init_mcp_deps, get_storage, get_token_manager,
)
from agora.coordinator.mcp.auth import (
    MCPAuthMiddleware, MCP_AUTH_WHITELIST,
    _extract_bearer_token, _validate_token,
    register_agent_session, unregister_agent_session,
    get_session_id_for_agent, get_agent_id_for_session,
)
from agora.coordinator.mcp.session_map import MCPSessionMap
from agora.coordinator.mcp.health import health_route
from agora.coordinator.rbac import Role


# --- Fixtures ---

class FakeTokenPayload:
    def __init__(self, agent_id="test-agent", role="agent"):
        self.agent_id = agent_id
        self.role = role


class FakeTokenManager:
    def __init__(self, valid=True, payload=None):
        self._valid = valid
        self._payload = payload or FakeTokenPayload()

    def validate_token(self, token: str):
        if not self._valid:
            raise ValueError("Invalid token")
        return self._payload


# --- Deps tests ---

class TestMCPDeps:
    def test_init_and_get(self):
        storage = MagicMock()
        token_mgr = FakeTokenManager()
        init_mcp_deps(storage, token_mgr=token_mgr)
        assert get_storage() is storage
        assert get_token_manager() is token_mgr

    def test_get_storage_raises_if_not_init(self):
        import agora.coordinator.mcp.deps as deps
        deps._storage = None
        with pytest.raises(RuntimeError, match="not initialized"):
            get_storage()

    def test_get_token_manager_none_by_default(self):
        import agora.coordinator.mcp.deps as deps
        deps._token_mgr = None
        assert get_token_manager() is None


# --- Auth helper tests ---

class TestAuthHelpers:
    def test_extract_bearer_token(self):
        from starlette.requests import Request
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [(b"authorization", b"Bearer test-token-123")],
        }
        req = Request(scope)
        assert _extract_bearer_token(req) == "test-token-123"

    def test_extract_bearer_token_missing(self):
        from starlette.requests import Request
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [],
        }
        req = Request(scope)
        assert _extract_bearer_token(req) == ""

    def test_whitelist_mcp_health(self):
        assert "/mcp/health" in MCP_AUTH_WHITELIST

    def test_validate_admin_token(self):
        result = _validate_token("admin-secret", None, "admin-secret")
        assert result == ("admin", Role.ADMIN)

    def test_validate_jwt_token(self):
        mgr = FakeTokenManager(valid=True)
        result = _validate_token("jwt-token", mgr, "")
        assert result is not None
        assert result[0] == "test-agent"
        assert result[1] == Role.AGENT

    def test_validate_agent_token(self):
        result = _validate_token("ag-abc123", None, "")
        assert result is not None
        assert result[0] == "ag-abc123"
        assert result[1] == Role.AGENT

    def test_validate_invalid_token(self):
        mgr = FakeTokenManager(valid=False)
        result = _validate_token("bad-token", mgr, "")
        assert result is None


# --- Session mapping tests ---

class TestSessionMapping:
    def test_register_and_lookup(self):
        register_agent_session("agent-1", "session-1")
        assert get_session_id_for_agent("agent-1") == "session-1"
        assert get_agent_id_for_session("session-1") == "agent-1"

    def test_unregister_session(self):
        register_agent_session("agent-2", "session-2")
        unregister_agent_session("session-2")
        assert get_session_id_for_agent("agent-2") is None
        assert get_agent_id_for_session("session-2") is None

    def test_session_overwrite(self):
        register_agent_session("agent-3", "session-3a")
        register_agent_session("agent-3", "session-3b")
        assert get_session_id_for_agent("agent-3") == "session-3b"
        # Old session should be cleaned up
        assert get_agent_id_for_session("session-3a") is None


# --- MCPSessionMap class tests ---

class TestMCPSessionMap:
    def test_register_and_lookup(self):
        sm = MCPSessionMap()
        sm.register("agent-1", "sess-1")
        assert sm.get_session_id("agent-1") == "sess-1"
        assert sm.get_agent_id("sess-1") == "agent-1"

    def test_unregister(self):
        sm = MCPSessionMap()
        sm.register("agent-2", "sess-2")
        sm.unregister_session("sess-2")
        assert sm.get_session_id("agent-2") is None

    def test_connected_agents(self):
        sm = MCPSessionMap()
        sm.register("a1", "s1")
        sm.register("a2", "s2")
        assert sorted(sm.connected_agents) == ["a1", "a2"]
        assert sm.session_count == 2

    def test_clear(self):
        sm = MCPSessionMap()
        sm.register("a1", "s1")
        sm.clear()
        assert sm.session_count == 0


# --- MCP app creation test ---

class TestMCPServerApp:
    def test_create_mcp_app_returns_starlette(self):
        app = create_mcp_app()
        from starlette.applications import Starlette
        assert isinstance(app, Starlette)

    def test_mcp_server_has_name(self):
        assert mcp_server.name is not None
        assert len(mcp_server.name) > 0

    def test_health_route_exists(self):
        assert health_route is not None
        assert health_route.path == "/health"
