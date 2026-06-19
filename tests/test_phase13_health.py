"""Phase 13.7b: Health check endpoint tests."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agora.coordinator.health import router, _VERSION


class TestHealthRoute:
    """Tests for GET /api/v1/health."""

    def test_health_router_has_health_path(self):
        """Router declares a GET /health route."""
        paths = [r.path for r in router.routes]
        assert "/health" in paths

    def test_health_version_is_0_13(self):
        """Health module version matches Phase 13."""
        assert _VERSION == "0.16.0"

    @pytest.mark.asyncio
    async def test_health_returns_expected_fields(self):
        """Health endpoint returns all required fields."""
        from agora.coordinator.main import create_app

        app = create_app()
        transport = ASGITransport(app=app)

        # Mock tenant_mgr.list_tenants to avoid DB dependency
        mock_tenant_mgr = MagicMock()
        mock_tenant_mgr.list_tenants = AsyncMock(return_value=[])

        with patch.object(
            app.state, "tenant_mgr", mock_tenant_mgr, create=True,
        ):
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.get("/api/v1/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["version"] == "0.16.0"
        assert "uptime_seconds" in data
        assert "agents_connected" in data
        assert "tenants" in data
        assert "db_size_mb" in data
        assert isinstance(data["uptime_seconds"], float)
        assert isinstance(data["agents_connected"], int)

    def test_health_route_registered_in_app(self):
        """Health route is registered under /api/v1/health."""
        from agora.coordinator.main import create_app

        app = create_app()
        paths = [getattr(r, "path", "") for r in app.routes]
        assert "/api/v1/health" in paths

    def test_legacy_health_redirect(self):
        """Legacy /health redirects to /api/v1/health."""
        from agora.coordinator.main import create_app

        app = create_app()
        paths = [getattr(r, "path", "") for r in app.routes]
        assert "/health" in paths
