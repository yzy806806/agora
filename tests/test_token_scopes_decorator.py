"""Tests for @requires_scope decorator — Phase 14+.E.6."""
import os
import pytest
from unittest.mock import patch
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from agora.coordinator.rbac import (
    requires_scope, get_current_scopes, rbac_enforced,
)
from agora.coordinator.token_scopes import TokenScope


def _make_app():
    app = FastAPI()

    @app.get("/read")
    @requires_scope(TokenScope.READ_WORKSPACE)
    async def read_ep(
        _rbac_scopes: list[str] | None = Depends(get_current_scopes),
    ):
        return {"ok": True}

    @app.get("/admin")
    @requires_scope(TokenScope.ADMIN)
    async def admin_ep(
        _rbac_scopes: list[str] | None = Depends(get_current_scopes),
    ):
        return {"ok": True}

    @app.get("/multi")
    @requires_scope("workspace:read", "workspace:write")
    async def multi_ep(
        _rbac_scopes: list[str] | None = Depends(get_current_scopes),
    ):
        return {"ok": True}

    return app


class TestRequiresScope:
    @pytest.fixture(autouse=True)
    def _enforce(self):
        with patch.dict(os.environ, {"AGORA_RBAC_ENFORCE": "true"}):
            yield

    def test_no_scopes_granted_all(self):
        """None scopes (old token) → all scopes granted."""
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        # Manually inject scopes via middleware-like state
        from starlette.middleware.base import BaseHTTPMiddleware

        class InjectMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state._rbac_scopes = None
                return await call_next(request)

        app.add_middleware(InjectMiddleware)
        resp = client.get("/admin")
        assert resp.status_code == 200

    def test_scope_match(self):
        app = _make_app()
        from starlette.middleware.base import BaseHTTPMiddleware

        class InjectMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state._rbac_scopes = ["workspace:read"]
                return await call_next(request)

        app.add_middleware(InjectMiddleware)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/read")
        assert resp.status_code == 200

    def test_scope_denied(self):
        app = _make_app()
        from starlette.middleware.base import BaseHTTPMiddleware

        class InjectMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state._rbac_scopes = ["workspace:read"]
                return await call_next(request)

        app.add_middleware(InjectMiddleware)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/admin")
        assert resp.status_code == 403
