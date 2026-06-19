"""Tests for Phase 15.A: Dashboard mandatory authentication.

Covers:
- Login endpoint returns JWT + Set-Cookie
- Logout endpoint clears cookie
- /dashboard redirects to /login without auth
- /dashboard returns HTML with valid cookie
- /dashboard returns HTML with valid Authorization header
- Login fails when AGORA_DASHBOARD_USERS not configured
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agora.coordinator.auth_router import router, init_auth_deps, COOKIE_NAME
from agora.coordinator.token_manager import TokenManager


def _create_app() -> tuple[FastAPI, TestClient, TokenManager]:
    """Create a minimal FastAPI app with auth router."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    token_mgr = TokenManager(secret="test-secret-key-for-phase15")
    init_auth_deps(token_mgr)
    client = TestClient(app)
    return app, client, token_mgr


class TestLoginEndpoint:
    """POST /api/v1/auth/login tests."""

    def test_login_returns_jwt_and_cookie(self):
        _, client, _ = _create_app()
        with patch("agora.coordinator.auth_router.parse_dashboard_users",
                    return_value={"admin": "hashedpw"}), \
             patch("agora.coordinator.auth_router.verify_password",
                    return_value=True):
            resp = client.post("/api/v1/auth/login", json={
                "username": "admin", "password": "test",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["role"] == "admin"
        # Check Set-Cookie header
        cookies = resp.cookies
        assert COOKIE_NAME in cookies

    def test_login_first_user_is_admin(self):
        _, client, _ = _create_app()
        users = {"alice": "h1", "bob": "h2"}
        with patch("agora.coordinator.auth_router.parse_dashboard_users",
                    return_value=users), \
             patch("agora.coordinator.auth_router.verify_password",
                    return_value=True):
            resp = client.post("/api/v1/auth/login", json={
                "username": "bob", "password": "test",
            })
        assert resp.status_code == 200
        assert resp.json()["role"] == "observer"

    def test_login_invalid_credentials(self):
        _, client, _ = _create_app()
        with patch("agora.coordinator.auth_router.parse_dashboard_users",
                    return_value={"admin": "hashedpw"}), \
             patch("agora.coordinator.auth_router.verify_password",
                    return_value=False):
            resp = client.post("/api/v1/auth/login", json={
                "username": "admin", "password": "wrong",
            })
        assert resp.status_code == 401

    def test_login_not_configured(self):
        _, client, _ = _create_app()
        with patch("agora.coordinator.auth_router.parse_dashboard_users",
                    return_value={}):
            resp = client.post("/api/v1/auth/login", json={
                "username": "admin", "password": "test",
            })
        assert resp.status_code == 501


class TestLogoutEndpoint:
    """POST /api/v1/auth/logout tests."""

    def test_logout_clears_cookie(self):
        _, client, _ = _create_app()
        resp = client.post("/api/v1/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["status"] == "logged_out"
        # Cookie should be cleared (max_age=0)
        set_cookie = resp.headers.get("set-cookie", "")
        assert COOKIE_NAME in set_cookie
        assert "Max-Age=0" in set_cookie


class TestDashboardRedirect:
    """/dashboard route redirect tests via main.py."""

    def _create_full_app(self) -> TestClient:
        """Create full app with dashboard route."""
        from agora.coordinator.main import create_app
        with patch.dict(os.environ, {
            "AGORA_JWT_SECRET": "test-secret-phase15",
            "AGORA_DATABASE_BACKEND": "sqlite",
        }):
            app = create_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_dashboard_no_auth_redirects_to_login(self):
        client = self._create_full_app()
        resp = client.get("/dashboard", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers.get("location", "")

    def test_dashboard_with_valid_cookie(self):
        client = self._create_full_app()
        tm = TokenManager(secret="test-secret-phase15")
        token = tm.create_token(
            agent_id="dashboard_user:admin", role="admin",
        )
        resp = client.get("/dashboard", cookies={COOKIE_NAME: token})
        assert resp.status_code == 200
        assert "dashboard" in resp.text.lower()

    def test_dashboard_with_valid_bearer(self):
        client = self._create_full_app()
        tm = TokenManager(secret="test-secret-phase15")
        token = tm.create_token(
            agent_id="dashboard_user:admin", role="admin",
        )
        resp = client.get("/dashboard", headers={
            "Authorization": f"Bearer {token}",
        })
        assert resp.status_code == 200

    def test_dashboard_with_expired_token_redirects(self):
        client = self._create_full_app()
        tm = TokenManager(secret="test-secret-phase15")
        token = tm.create_token(
            agent_id="dashboard_user:admin", role="admin",
            expires_delta=-1,  # already expired
        )
        resp = client.get("/dashboard", cookies={COOKIE_NAME: token},
                          follow_redirects=False)
        assert resp.status_code == 302

    def test_login_page_returns_html(self):
        client = self._create_full_app()
        resp = client.get("/login")
        assert resp.status_code == 200
        assert "login" in resp.text.lower()
