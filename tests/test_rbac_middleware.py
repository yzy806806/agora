"""Tests for Phase 10.2a: RBAC Middleware + @requires decorator."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agora.coordinator.rbac import Permission, Role, requires, rbac_enforced
from agora.coordinator.rbac_middleware import RBACMiddleware, _resolve_role_and_scopes


class TestRbacEnforced:
    def test_default_off(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove AGORA_RBAC_ENFORCE if present
            os.environ.pop("AGORA_RBAC_ENFORCE", None)
            assert not rbac_enforced()

    def test_enabled_true(self):
        with patch.dict(os.environ, {"AGORA_RBAC_ENFORCE": "true"}):
            assert rbac_enforced()

    def test_enabled_1(self):
        with patch.dict(os.environ, {"AGORA_RBAC_ENFORCE": "1"}):
            assert rbac_enforced()

    def test_disabled_false(self):
        with patch.dict(os.environ, {"AGORA_RBAC_ENFORCE": "false"}):
            assert not rbac_enforced()


class TestRequiresDecorator:
    @pytest.mark.asyncio
    async def test_noop_when_not_enforced(self):
        @requires(Permission.ADMIN_FULL)
        async def handler():
            return "ok"

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AGORA_RBAC_ENFORCE", None)
            result = await handler()
            assert result == "ok"

    @pytest.mark.asyncio
    async def test_allowed_when_enforced(self):
        @requires(Permission.TASK_EXECUTE)
        async def handler(_rbac_role: str = "agent"):
            return "ok"

        with patch.dict(os.environ, {"AGORA_RBAC_ENFORCE": "true"}):
            result = await handler(_rbac_role="agent")
            assert result == "ok"

    @pytest.mark.asyncio
    async def test_forbidden_when_enforced(self):
        from fastapi import HTTPException

        @requires(Permission.ADMIN_FULL)
        async def handler(_rbac_role: str = "observer"):
            return "ok"

        with patch.dict(os.environ, {"AGORA_RBAC_ENFORCE": "true"}):
            with pytest.raises(HTTPException) as exc_info:
                await handler(_rbac_role="observer")
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_unauthenticated_when_no_role(self):
        from fastapi import HTTPException

        @requires(Permission.TASK_EXECUTE)
        async def handler():
            return "ok"

        with patch.dict(os.environ, {"AGORA_RBAC_ENFORCE": "true"}):
            with pytest.raises(HTTPException) as exc_info:
                await handler()
            assert exc_info.value.status_code == 401


class TestResolveRole:
    def test_admin_token_gets_admin(self):
        from starlette.testclient import TestClient as _TC
        from starlette.requests import Request

        scope = {
            "type": "http", "method": "GET", "path": "/",
            "headers": [(b"authorization", b"Bearer myadmin")],
            "query_string": b"", "server": ("test", 80),
        }
        with patch("agora.coordinator.rbac_middleware.settings") as mock_s:
            mock_s.admin_token = "myadmin"
            req = Request(scope)
            role, scopes = _resolve_role_and_scopes(req)
            assert role == Role.ADMIN
            assert scopes is None  # admin → all scopes

    def test_agent_token_gets_agent(self):
        from starlette.requests import Request

        scope = {
            "type": "http", "method": "GET", "path": "/",
            "headers": [(b"authorization", b"Bearer ag-abc123")],
            "query_string": b"", "server": ("test", 80),
        }
        with patch("agora.coordinator.rbac_middleware.settings") as mock_s:
            mock_s.admin_token = "other"
            req = Request(scope)
            role, scopes = _resolve_role_and_scopes(req)
            assert role == Role.AGENT

    def test_no_token_gets_observer(self):
        from starlette.requests import Request

        scope = {
            "type": "http", "method": "GET", "path": "/",
            "headers": [],
            "query_string": b"", "server": ("test", 80),
        }
        req = Request(scope)
        role, scopes = _resolve_role_and_scopes(req)
        assert role == Role.OBSERVER
