"""Phase 11.5a: event bus + router registration + backward compat tests.

Removed: test_plugin_routes_registered (plugin system removed).
"""
from __future__ import annotations

import pytest

from agora.coordinator.event_bus import init_event_bus, publish
from agora.coordinator.dashboard_ws import DashboardHub
from agora.coordinator.token_manager import TokenManager
from agora.coordinator.main import create_app


def _get_route_paths(app) -> list[str]:
    """Extract all route paths from a FastAPI app."""
    paths = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if path:
            paths.append(path)
    return paths


class TestEventBus:
    """Tests for event_bus.publish()."""

    def test_publish_without_init(self):
        """Publish returns 0 when hub not initialized."""
        import agora.coordinator.event_bus as eb
        old = eb._dashboard_hub
        eb._dashboard_hub = None
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            publish("TEST", {"key": "val"}),
        )
        assert result == 0
        eb._dashboard_hub = old

    def test_publish_with_hub(self):
        """Publish forwards events to dashboard hub."""
        hub = DashboardHub()
        hub.set_token_manager(TokenManager(secret="test"))
        init_event_bus(hub)
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            publish("TEST_EVENT", {"detail": "hello"}, channel="events"),
        )
        # No clients connected, so count is 0
        assert result == 0


class TestRouterRegistration:
    """Verify Phase 11 routers are registered in create_app()."""

    def test_auth_router_registered(self):
        app = create_app()
        paths = _get_route_paths(app)
        assert "/api/v1/auth/login" in paths

    def test_dashboard_ws_registered(self):
        app = create_app()
        paths = _get_route_paths(app)
        assert any("/ws/dashboard" in p for p in paths)

    def test_audit_query_registered(self):
        app = create_app()
        paths = _get_route_paths(app)
        assert "/api/v1/admin/audit" in paths

    def test_task_query_routes_registered(self):
        app = create_app()
        paths = _get_route_paths(app)
        assert "/api/v1/tasks" in paths

    def test_task_graph_routes_registered(self):
        app = create_app()
        paths = _get_route_paths(app)
        assert "/api/v1/task-graphs" in paths


class TestBackwardCompat:
    """Verify backward compatibility when AGORA_DASHBOARD_USERS not set."""

    def test_dashboard_page_accessible(self):
        app = create_app()
        paths = _get_route_paths(app)
        assert "/dashboard" in paths

    def test_health_endpoint_works(self):
        app = create_app()
        paths = _get_route_paths(app)
        assert "/health" in paths
