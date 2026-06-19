"""Tests for Phase 15.C: Registration API + approval flow.

Part 2: HTTP endpoint integration tests.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agora.coordinator.router import router, init_deps
from agora.coordinator.config import settings


def _make_client(require_approval: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    storage = AsyncMock()
    sm = AsyncMock()
    init_deps(storage, sm)
    return TestClient(app)


class TestRegisterEndpoint:
    """Test POST /agents/register without auth."""

    def test_register_returns_429_on_rate_limit(self):
        client = _make_client()
        # Patch storage to avoid actual DB
        with patch("agora.coordinator.router._storage") as ms:
            ms.get_agent = AsyncMock(return_value=None)
            ms.register_agent = AsyncMock(return_value={"agent_id": "x"})
            # Exhaust rate limit
            for _ in range(3):
                client.post("/api/v1/agents/register", json={
                    "agent_id": f"a{_}", "name": "A",
                })
            # 4th should be 429
            resp = client.post("/api/v1/agents/register", json={
                "agent_id": "a_extra", "name": "A",
            })
            assert resp.status_code == 429

    def test_register_no_auth_required(self):
        """Registration endpoint should work without Bearer token."""
        client = _make_client()
        with patch("agora.coordinator.router._storage") as ms:
            ms.get_agent = AsyncMock(return_value=None)
            ms.register_agent = AsyncMock(return_value={"agent_id": "new"})
            # Reset rate limiter
            from agora.coordinator.router import _reg_rate_limiter
            if _reg_rate_limiter:
                _reg_rate_limiter.reset()
            resp = client.post("/api/v1/agents/register", json={
                "agent_id": "new", "name": "NewAgent",
            })
            assert resp.status_code == 201


class TestRegistrationStatusEndpoint:
    """Test GET /agents/register/{agent_id}/status."""

    def test_status_with_valid_token(self):
        client = _make_client()
        with patch("agora.coordinator.router._storage") as ms:
            ms.get_agent = AsyncMock(return_value={
                "agent_id": "a1",
                "registration_token": "reg-abc",
                "approval_status": "pending",
            })
            resp = client.get(
                "/api/v1/agents/register/a1/status",
                headers={"X-Registration-Token": "reg-abc"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["approval_status"] == "pending"

    def test_status_invalid_token_403(self):
        client = _make_client()
        with patch("agora.coordinator.router._storage") as ms:
            ms.get_agent = AsyncMock(return_value={
                "agent_id": "a1",
                "registration_token": "reg-abc",
                "approval_status": "pending",
            })
            resp = client.get(
                "/api/v1/agents/register/a1/status",
                headers={"X-Registration-Token": "wrong"},
            )
            assert resp.status_code == 403

    def test_status_agent_not_found(self):
        client = _make_client()
        with patch("agora.coordinator.router._storage") as ms:
            ms.get_agent = AsyncMock(return_value=None)
            resp = client.get(
                "/api/v1/agents/register/nope/status",
                headers={"X-Registration-Token": "any"},
            )
            assert resp.status_code == 404

    def test_status_approved_returns_agent_token(self):
        client = _make_client()
        with patch("agora.coordinator.router._storage") as ms:
            ms.get_agent = AsyncMock(return_value={
                "agent_id": "a1",
                "registration_token": "reg-abc",
                "approval_status": "approved",
                "agent_token": "ag-secret",
            })
            ms.clear_registration_token = AsyncMock()
            resp = client.get(
                "/api/v1/agents/register/a1/status",
                headers={"X-Registration-Token": "reg-abc"},
            )
            data = resp.json()
            assert data["agent_token"] == "ag-secret"
            # Token must be cleared after one-time read
            ms.clear_registration_token.assert_called_once_with("a1")

    def test_status_approved_with_empty_reg_token(self):
        """Edge case: approval with registration_token="" should 403.

        If registration_token was already cleared (or never set for
        an auto-approved agent), the status endpoint must reject
        the request — there's no token to authenticate with.
        """
        client = _make_client()
        with patch("agora.coordinator.router._storage") as ms:
            ms.get_agent = AsyncMock(return_value={
                "agent_id": "a2",
                "registration_token": "",
                "approval_status": "approved",
                "agent_token": "ag-xyz",
            })
            resp = client.get(
                "/api/v1/agents/register/a2/status",
                headers={"X-Registration-Token": ""},
            )
            assert resp.status_code == 403

    def test_status_pending_does_not_clear_token(self):
        """Pending agents should NOT have their token cleared."""
        client = _make_client()
        with patch("agora.coordinator.router._storage") as ms:
            ms.get_agent = AsyncMock(return_value={
                "agent_id": "a3",
                "registration_token": "reg-pending",
                "approval_status": "pending",
            })
            resp = client.get(
                "/api/v1/agents/register/a3/status",
                headers={"X-Registration-Token": "reg-pending"},
            )
            assert resp.status_code == 200
            # Token should NOT be cleared for pending status
            ms.clear_registration_token.assert_not_called()
