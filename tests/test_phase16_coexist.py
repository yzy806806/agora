"""Phase 16.6c: Integration test — REST + WS + MCP coexistence.

Verifies that mounting MCP at /mcp does not break existing
REST API or WebSocket endpoints, and all three protocols
can be accessed simultaneously.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from agora.coordinator.main import create_app


def test_mcp_mount_exists():
    """MCP sub-app is mounted at /mcp in the FastAPI app."""
    app = create_app()
    # Mount routes appear as Mount objects
    mount_paths = [
        r.path for r in app.routes
        if type(r).__name__ == "Mount"
    ]
    assert "/mcp" in mount_paths


def test_rest_routes_still_exist():
    """REST API routes are still registered after MCP mount."""
    app = create_app()
    paths = [r.path for r in app.routes]
    assert "/api/v1/agents/register" in paths or any(
        "agents/register" in getattr(r, "path", "")
        for r in app.routes
    )


def test_ws_route_still_exists():
    """WebSocket route still exists after MCP mount."""
    app = create_app()
    ws_paths = [
        r.path for r in app.routes
        if hasattr(r, "path") and "/ws" in r.path
    ]
    assert len(ws_paths) > 0


def test_health_routes_no_conflict():
    """REST /health and MCP /mcp/health don't conflict."""
    app = create_app()
    paths = [r.path for r in app.routes]
    # REST health at root level
    assert "/health" in paths
    # MCP health is inside the /mcp mount, not at root level
    assert "/mcp/health" not in paths


@pytest.mark.asyncio
async def test_rest_health_via_app():
    """REST /api/v1/health works when MCP is mounted."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
    ) as client:
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_mcp_health_via_app():
    """MCP /mcp/health works when mounted in full app."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
    ) as client:
        resp = await client.get("/mcp/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "agora-mcp"
