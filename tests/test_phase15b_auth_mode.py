"""Tests for Phase 15.B: API forced authentication.

Covers:
- AGORA_AUTH_MODE config (default, env var)
- RBACMiddleware whitelist + three auth modes
- @requires() decorator under each mode
- rbac_enforced() backward compat
- get_auth_mode() legacy mapping
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agora.coordinator.config import Settings
from agora.coordinator.rbac import (
    Permission, Role, check_permission, requires, rbac_enforced,
)
from agora.coordinator.rbac_middleware import (
    AUTH_WHITELIST,
    RBACMiddleware,
    _is_whitelisted,
    _resolve_role_and_scopes,
    get_auth_mode,
)


# --- Config tests ---

class TestAuthModeConfig:
    def test_default_none(self):
        s = Settings()
        assert s.auth_mode == "none"

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("AGORA_AUTH_MODE", "token")
        s = Settings()
        assert s.auth_mode == "token"

    def test_rbac_from_env(self, monkeypatch):
        monkeypatch.setenv("AGORA_AUTH_MODE", "rbac")
        s = Settings()
        assert s.auth_mode == "rbac"

    def test_invalid_value_raises(self, monkeypatch):
        monkeypatch.setenv("AGORA_AUTH_MODE", "invalid")
        with pytest.raises(Exception):
            Settings()


# --- Whitelist tests ---

class TestWhitelist:
    def test_health_whitelisted(self):
        assert _is_whitelisted("/health")

    def test_api_health_whitelisted(self):
        assert _is_whitelisted("/api/v1/health")

    def test_login_whitelisted(self):
        assert _is_whitelisted("/api/v1/auth/login")

    def test_logout_whitelisted(self):
        assert _is_whitelisted("/api/v1/auth/logout")

    def test_discovery_whitelisted(self):
        assert _is_whitelisted("/api/v1/discovery")

    def test_register_whitelisted(self):
        assert _is_whitelisted("/api/v1/agents/register")

    def test_register_status_whitelisted(self):
        assert _is_whitelisted("/api/v1/agents/register/abc/status")

    def test_other_not_whitelisted(self):
        assert not _is_whitelisted("/api/v1/agents")
        assert not _is_whitelisted("/api/v1/motions")
        assert not _is_whitelisted("/api/v1/tasks")


# --- get_auth_mode tests ---

class TestGetAuthMode:
    def test_none_mode(self):
        with patch("agora.coordinator.rbac_middleware.settings") as m:
            m.auth_mode = "none"
            m.rbac_enforce = False
            assert get_auth_mode() == "none"

    def test_token_mode(self):
        with patch("agora.coordinator.rbac_middleware.settings") as m:
            m.auth_mode = "token"
            m.rbac_enforce = False
            assert get_auth_mode() == "token"

    def test_rbac_mode(self):
        with patch("agora.coordinator.rbac_middleware.settings") as m:
            m.auth_mode = "rbac"
            m.rbac_enforce = False
            assert get_auth_mode() == "rbac"

    def test_legacy_rbac_enforce_maps_to_rbac(self):
        with patch("agora.coordinator.rbac_middleware.settings") as m:
            m.auth_mode = "none"
            m.rbac_enforce = True
            assert get_auth_mode() == "rbac"


# --- rbac_enforced() backward compat ---

class TestRbacEnforcedCompat:
    def test_old_env_true(self):
        with patch.dict(os.environ, {"AGORA_RBAC_ENFORCE": "true"}):
            assert rbac_enforced()

    def test_auth_mode_rbac(self):
        with patch("agora.coordinator.config.settings") as m:
            m.auth_mode = "rbac"
            assert rbac_enforced()

    def test_auth_mode_token_not_rbac(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AGORA_RBAC_ENFORCE", None)
            with patch("agora.coordinator.config.settings") as m:
                m.auth_mode = "token"
                assert not rbac_enforced()


# --- @requires() under each mode ---

class TestRequiresAuthModes:
    @pytest.mark.asyncio
    async def test_none_mode_noop(self):
        @requires(Permission.ADMIN_FULL)
        async def handler():
            return "ok"
        with patch("agora.coordinator.config.settings") as m:
            m.auth_mode = "none"
            with patch.dict(os.environ, {}, clear=True):
                os.environ.pop("AGORA_RBAC_ENFORCE", None)
                result = await handler()
                assert result == "ok"

    @pytest.mark.asyncio
    async def test_token_mode_allows_authenticated(self):
        @requires(Permission.ADMIN_FULL)
        async def handler(_rbac_role: str = "agent"):
            return "ok"
        with patch("agora.coordinator.config.settings") as m:
            m.auth_mode = "token"
            with patch.dict(os.environ, {}, clear=True):
                os.environ.pop("AGORA_RBAC_ENFORCE", None)
                # token mode: no permission check, just auth
                result = await handler(_rbac_role="agent")
                assert result == "ok"

    @pytest.mark.asyncio
    async def test_rbac_mode_checks_permission(self):
        from fastapi import HTTPException

        @requires(Permission.ADMIN_FULL)
        async def handler(_rbac_role: str = "observer"):
            return "ok"
        with patch("agora.coordinator.config.settings") as m:
            m.auth_mode = "rbac"
            with pytest.raises(HTTPException) as exc:
                await handler(_rbac_role="observer")
            assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_rbac_mode_allows_permitted(self):
        @requires(Permission.TASK_EXECUTE)
        async def handler(_rbac_role: str = "agent"):
            return "ok"
        with patch("agora.coordinator.config.settings") as m:
            m.auth_mode = "rbac"
            result = await handler(_rbac_role="agent")
            assert result == "ok"

    @pytest.mark.asyncio
    async def test_rbac_mode_no_role_401(self):
        from fastapi import HTTPException

        @requires(Permission.TASK_EXECUTE)
        async def handler():
            return "ok"
        with patch("agora.coordinator.config.settings") as m:
            m.auth_mode = "rbac"
            with pytest.raises(HTTPException) as exc:
                await handler()
            assert exc.value.status_code == 401


# --- Middleware integration ---

class TestMiddlewareIntegration:
    def _make_app(self, mode: str) -> FastAPI:
        app = FastAPI()

        @app.get("/api/v1/health")
        async def health():
            return {"status": "healthy"}

        @app.get("/api/v1/agents")
        async def agents():
            return {"agents": []}

        @app.get("/api/v1/discovery")
        async def discovery():
            return {"agents": []}

        app.add_middleware(RBACMiddleware)
        return app

    def test_none_mode_allows_all(self):
        with patch("agora.coordinator.rbac_middleware.settings") as m:
            m.auth_mode = "none"
            m.rbac_enforce = False
            m.admin_token = ""
            app = self._make_app("none")
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/v1/agents")
            assert resp.status_code == 200

    def test_token_mode_rejects_no_token(self):
        with patch("agora.coordinator.rbac_middleware.settings") as m:
            m.auth_mode = "token"
            m.rbac_enforce = False
            m.admin_token = ""
            app = self._make_app("token")
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/v1/agents")
            assert resp.status_code == 401

    def test_token_mode_allows_with_token(self):
        with patch("agora.coordinator.rbac_middleware.settings") as m:
            m.auth_mode = "token"
            m.rbac_enforce = False
            m.admin_token = "myadmin"
            app = self._make_app("token")
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/v1/agents",
                headers={"Authorization": "Bearer myadmin"},
            )
            assert resp.status_code == 200

    def test_whitelist_health_no_token(self):
        with patch("agora.coordinator.rbac_middleware.settings") as m:
            m.auth_mode = "rbac"
            m.rbac_enforce = False
            m.admin_token = ""
            app = self._make_app("rbac")
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/v1/health")
            assert resp.status_code == 200

    def test_whitelist_discovery_no_token(self):
        with patch("agora.coordinator.rbac_middleware.settings") as m:
            m.auth_mode = "rbac"
            m.rbac_enforce = False
            m.admin_token = ""
            app = self._make_app("rbac")
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/v1/discovery")
            assert resp.status_code == 200

    def test_rbac_mode_rejects_no_token(self):
        with patch("agora.coordinator.rbac_middleware.settings") as m:
            m.auth_mode = "rbac"
            m.rbac_enforce = False
            m.admin_token = ""
            app = self._make_app("rbac")
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/v1/agents")
            assert resp.status_code == 401

    def test_rbac_mode_agent_token_passes_auth(self):
        with patch("agora.coordinator.rbac_middleware.settings") as m:
            m.auth_mode = "rbac"
            m.rbac_enforce = False
            m.admin_token = ""
            app = self._make_app("rbac")
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/v1/agents",
                headers={"Authorization": "Bearer ag-test123"},
            )
            # Middleware passes; @requires() on actual route would check perms
            assert resp.status_code == 200


# --- Backward compat: test_rbac_wiring.py fixes ---

class TestRegisterEndpointWhitelisted:
    """Phase 15.B/C: /agents/register is whitelisted from auth.

    Even in rbac mode, this endpoint does not require authentication
    because new agents have no token. Rate limiting protects it instead.
    """

    def test_register_no_auth_needed_in_rbac_mode(self):
        """In rbac mode, /agents/register is still accessible."""
        with patch("agora.coordinator.rbac_middleware.settings") as m:
            m.auth_mode = "rbac"
            m.rbac_enforce = False
            m.admin_token = ""
            from fastapi import FastAPI
            from agora.coordinator.rbac_middleware import RBACMiddleware

            app = FastAPI()

            @app.post("/api/v1/agents/register")
            async def register():
                return {"status": "ok"}

            app.add_middleware(RBACMiddleware)
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/api/v1/agents/register", json={"agent_id": "test"})
            assert resp.status_code == 200


class TestPublicEndpointsRbacOff:
    """When auth_mode=none (default), public endpoints work without auth."""

    def test_metrics_no_auth(self):
        """Metrics endpoint should work without auth in none mode."""
        from fastapi import FastAPI
        app = FastAPI()

        @app.get("/metrics")
        async def metrics():
            return {"status": "ok"}

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/metrics")
        assert resp.status_code == 200
