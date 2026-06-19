"""Tests for Phase 16.5: MCP Auth Integration.

Covers:
- 16.5a: MCP endpoints in RBAC whitelist
- 16.5b: MCPAuthMiddleware with TokenManager + agent token
- 16.5c: Three token types (JWT / ag-* / admin)
"""
from __future__ import annotations

import pytest
from unittest.mock import patch
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from agora.coordinator.mcp.auth import (
    MCPAuthMiddleware,
    _validate_token,
    get_agent_id_from_state,
    get_role_from_state,
    is_authenticated,
    MCP_AUTH_WHITELIST,
    _MCP_AGENT_ID,
    _MCP_ROLE,
    _MCP_AUTHENTICATED,
)
from agora.coordinator.rbac import Role
from agora.coordinator.rbac_middleware import AUTH_WHITELIST, _is_whitelisted
from agora.coordinator.token_manager import TokenManager


# --- Helper: minimal Starlette app with MCPAuthMiddleware ---

async def _echo_handler(request: Request):
    """Echo back auth state from request."""
    agent_id = getattr(request.state, _MCP_AGENT_ID, None)
    role = getattr(request.state, _MCP_ROLE, None)
    authed = getattr(request.state, _MCP_AUTHENTICATED, False)
    return JSONResponse({
        "agent_id": agent_id,
        "role": role.value if role else None,
        "authenticated": authed,
    })


async def _health_handler(request: Request):
    return JSONResponse({"status": "ok"})


def _make_app(token_mgr=None, admin_token=""):
    """Create a test Starlette app with MCPAuthMiddleware.

    Patches get_auth_mode to return "token" so auth is enforced.
    """
    app = Starlette(routes=[
        Route("/mcp/health", _health_handler),
        Route("/mcp/tools", _echo_handler, methods=["GET", "POST"]),
    ])
    app.add_middleware(
        MCPAuthMiddleware,
        token_mgr=token_mgr,
        admin_token=admin_token,
    )
    return app


# --- 16.5a: RBAC whitelist tests ---

class TestMCPWhitelist:
    """Verify /mcp paths are whitelisted in RBAC middleware."""

    def test_mcp_root_in_whitelist(self):
        assert "/mcp" in AUTH_WHITELIST

    def test_mcp_health_in_mcp_whitelist(self):
        assert "/mcp/health" in MCP_AUTH_WHITELIST

    def test_mcp_subpath_whitelisted(self):
        assert _is_whitelisted("/mcp/sse")

    def test_mcp_messages_whitelisted(self):
        assert _is_whitelisted("/mcp/messages")

    def test_mcp_root_whitelisted(self):
        assert _is_whitelisted("/mcp")


# --- 16.5b: _validate_token unit tests ---

class TestValidateToken:
    """Unit tests for _validate_token function."""

    def test_admin_token_valid(self):
        result = _validate_token("myadmin", None, "myadmin")
        assert result == ("admin", Role.ADMIN)

    def test_admin_token_wrong(self):
        result = _validate_token("wrong", None, "myadmin")
        assert result is None

    def test_jwt_token_valid(self):
        tm = TokenManager(secret="testsecret")
        jwt_token = tm.create_token(agent_id="agent-1", role="agent")
        result = _validate_token(jwt_token, tm, "otheradmin")
        assert result is not None
        assert result[0] == "agent-1"
        assert result[1] == Role.AGENT

    def test_jwt_token_expired(self):
        tm = TokenManager(secret="testsecret")
        jwt_token = tm.create_token(
            agent_id="agent-1", role="agent", expires_delta=-10,
        )
        result = _validate_token(jwt_token, tm, "otheradmin")
        assert result is None

    def test_agent_token_ag_prefix(self):
        result = _validate_token("ag-abc123xyz", None, "myadmin")
        assert result is not None
        assert result[0] == "ag-abc123xyz"
        assert result[1] == Role.AGENT

    def test_invalid_token_no_match(self):
        result = _validate_token("random-garbage", None, "myadmin")
        assert result is None

    def test_no_token_mgr_jwt_fails_gracefully(self):
        tm = TokenManager(secret="testsecret")
        jwt_token = tm.create_token(agent_id="a1", role="admin")
        result = _validate_token(jwt_token, None, "otheradmin")
        assert result is None


# --- 16.5c: MCPAuthMiddleware integration tests ---

@patch("agora.coordinator.rbac_middleware.get_auth_mode", return_value="token")
class TestMCPAuthMiddlewareJWT:
    """Test JWT token authentication through MCP middleware."""

    def test_valid_jwt_passes(self, _mock):
        tm = TokenManager(secret="testsecret")
        jwt_token = tm.create_token(
            agent_id="agent-42", role="agent",
        )
        app = _make_app(token_mgr=tm, admin_token="admin123")
        client = TestClient(app)
        resp = client.post(
            "/mcp/tools",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "agent-42"
        assert data["role"] == "agent"
        assert data["authenticated"] is True

    def test_expired_jwt_rejected(self, _mock):
        tm = TokenManager(secret="testsecret")
        jwt_token = tm.create_token(
            agent_id="agent-42", role="agent", expires_delta=-10,
        )
        app = _make_app(token_mgr=tm, admin_token="admin123")
        client = TestClient(app)
        resp = client.post(
            "/mcp/tools",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert resp.status_code == 401

    def test_jwt_admin_role(self, _mock):
        tm = TokenManager(secret="testsecret")
        jwt_token = tm.create_token(
            agent_id="admin-user", role="admin",
        )
        app = _make_app(token_mgr=tm, admin_token="other")
        client = TestClient(app)
        resp = client.post(
            "/mcp/tools",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "admin"


@patch("agora.coordinator.rbac_middleware.get_auth_mode", return_value="token")
class TestMCPAuthMiddlewareAgentToken:
    """Test ag-* agent token authentication."""

    def test_agent_token_passes(self, _mock):
        app = _make_app(token_mgr=None, admin_token="admin123")
        client = TestClient(app)
        resp = client.post(
            "/mcp/tools",
            headers={"Authorization": "Bearer ag-testtoken123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "ag-testtoken123"
        assert data["role"] == "agent"
        assert data["authenticated"] is True

    def test_agent_token_format(self, _mock):
        """ag- prefix is required for agent token recognition."""
        app = _make_app(token_mgr=None, admin_token="admin123")
        client = TestClient(app)
        resp = client.post(
            "/mcp/tools",
            headers={"Authorization": "Bearer xy-notagent"},
        )
        assert resp.status_code == 401


@patch("agora.coordinator.rbac_middleware.get_auth_mode", return_value="token")
class TestMCPAuthMiddlewareAdminToken:
    """Test admin token authentication."""

    def test_admin_token_passes(self, _mock):
        app = _make_app(token_mgr=None, admin_token="supersecret")
        client = TestClient(app)
        resp = client.post(
            "/mcp/tools",
            headers={"Authorization": "Bearer supersecret"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "admin"
        assert data["role"] == "admin"
        assert data["authenticated"] is True

    def test_wrong_admin_token_rejected(self, _mock):
        app = _make_app(token_mgr=None, admin_token="supersecret")
        client = TestClient(app)
        resp = client.post(
            "/mcp/tools",
            headers={"Authorization": "Bearer wrongsecret"},
        )
        assert resp.status_code == 401


@patch("agora.coordinator.rbac_middleware.get_auth_mode", return_value="token")
class TestMCPAuthMiddlewareEdgeCases:
    """Edge cases: missing token, whitelist, etc."""

    def test_missing_auth_header(self, _mock):
        app = _make_app(token_mgr=None, admin_token="admin123")
        client = TestClient(app)
        resp = client.post("/mcp/tools")
        assert resp.status_code == 401
        assert "Missing Authorization" in resp.json()["error"]

    def test_empty_bearer(self, _mock):
        app = _make_app(token_mgr=None, admin_token="admin123")
        client = TestClient(app)
        resp = client.post(
            "/mcp/tools",
            headers={"Authorization": "Bearer "},
        )
        assert resp.status_code == 401

    def test_invalid_token_rejected(self, _mock):
        app = _make_app(token_mgr=None, admin_token="admin123")
        client = TestClient(app)
        resp = client.post(
            "/mcp/tools",
            headers={"Authorization": "Bearer not-valid"},
        )
        assert resp.status_code == 401
        assert "Invalid token" in resp.json()["error"]

    def test_whitelist_health_no_auth(self, _mock):
        app = _make_app(token_mgr=None, admin_token="admin123")
        client = TestClient(app)
        resp = client.get("/mcp/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# --- Helper function tests ---

class TestGetAgentIdFromState:
    """Test get_agent_id_from_state with mock storage."""

    @pytest.mark.asyncio
    async def test_jwt_agent_id_returned_directly(self):
        req = _make_request_with_state(
            **{_MCP_AGENT_ID: "agent-42", _MCP_ROLE: Role.AGENT}
        )
        result = await get_agent_id_from_state(req, storage=None)
        assert result == "agent-42"

    @pytest.mark.asyncio
    async def test_admin_agent_id_returned(self):
        req = _make_request_with_state(
            **{_MCP_AGENT_ID: "admin", _MCP_ROLE: Role.ADMIN}
        )
        result = await get_agent_id_from_state(req, storage=None)
        assert result == "admin"

    @pytest.mark.asyncio
    async def test_ag_token_resolved_via_storage(self):
        from unittest.mock import AsyncMock
        storage = AsyncMock()
        storage.get_agent_by_token.return_value = {
            "agent_id": "real-agent-id",
        }
        req = _make_request_with_state(
            **{_MCP_AGENT_ID: "ag-abc123", _MCP_ROLE: Role.AGENT}
        )
        result = await get_agent_id_from_state(req, storage)
        assert result == "real-agent-id"
        storage.get_agent_by_token.assert_called_once_with("ag-abc123")

    @pytest.mark.asyncio
    async def test_ag_token_not_found_in_storage(self):
        from unittest.mock import AsyncMock
        storage = AsyncMock()
        storage.get_agent_by_token.return_value = None
        req = _make_request_with_state(
            **{_MCP_AGENT_ID: "ag-nonexistent", _MCP_ROLE: Role.AGENT}
        )
        result = await get_agent_id_from_state(req, storage)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_state_returns_none(self):
        req = _make_request_with_state()
        result = await get_agent_id_from_state(req, storage=None)
        assert result is None


class TestGetRoleFromState:
    def test_role_present(self):
        req = _make_request_with_state(**{_MCP_ROLE: Role.ADMIN})
        assert get_role_from_state(req) == Role.ADMIN

    def test_role_absent(self):
        req = _make_request_with_state()
        assert get_role_from_state(req) is None


class TestIsAuthenticated:
    def test_authenticated(self):
        req = _make_request_with_state(**{_MCP_AUTHENTICATED: True})
        assert is_authenticated(req) is True

    def test_not_authenticated(self):
        req = _make_request_with_state()
        assert is_authenticated(req) is False


# --- Test fixture helpers ---

class _FakeState:
    """Minimal request.state substitute for unit tests."""
    pass


def _make_request_with_state(**attrs):
    """Create a Request-like object with state attributes."""
    req = type("FakeRequest", (), {"state": _FakeState()})()
    for k, v in attrs.items():
        setattr(req.state, k, v)
    return req
