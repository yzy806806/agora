"""Tests for dashboard event storage and API endpoints."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from agora.coordinator.storage import Storage
from agora.coordinator.dashboard import init_dashboard_deps
from agora.coordinator.router import init_deps
from agora.coordinator.state import StateMachine
from agora.coordinator.main import create_app

@pytest_asyncio.fixture(loop_scope="session")
async def storage(tmp_path):
    db_path = str(tmp_path / "test_dashboard.db")
    s = Storage(db_path)
    await s.init_db()
    yield s


@pytest_asyncio.fixture(loop_scope="session")
async def client_and_app(storage):
    """Yield (httpx client, FastAPI app) for dashboard tests."""
    from agora.coordinator.token_manager import TokenManager
    from agora.coordinator.audit import AuditLogger
    from agora.coordinator.auth_router import init_auth_deps
    app = create_app()
    sm = StateMachine(storage)
    init_deps(storage, sm)
    init_dashboard_deps(storage)
    # Manually init token_mgr (lifespan doesn't run with ASGITransport)
    token_mgr = TokenManager()
    app.state.token_mgr = token_mgr
    init_auth_deps(token_mgr)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, app


# --- Storage-level tests ---

@pytest.mark.asyncio(loop_scope="session")
async def test_log_and_get_events(storage):
    eid = await storage.log_event("agent_connected", "Agent X joined")
    assert eid > 0
    events = await storage.get_events()
    assert len(events) >= 1
    assert events[0]["type"] == "agent_connected"


@pytest.mark.asyncio(loop_scope="session")
async def test_get_events_filter_by_type(storage):
    await storage.log_event("motion_started", "M1 started")
    await storage.log_event("agent_connected", "A1 joined")
    events = await storage.get_events(event_type="motion_started")
    assert all(e["type"] == "motion_started" for e in events)


@pytest.mark.asyncio(loop_scope="session")
async def test_get_events_with_since(storage):
    await storage.log_event("test_since", "before")
    events = await storage.get_events(since="2099-01-01T00:00:00")
    assert len(events) == 0


@pytest.mark.asyncio(loop_scope="session")
async def test_get_timeline(storage):
    motion = await storage.create_motion("Timeline Test", "desc")
    mid = motion["id"]
    await storage.register_agent("agent-1", "Agent One", "gpt-4")
    await storage.log_event("motion_started", "started", motion_id=mid)
    await storage.add_message(mid, "agent-1", 1, "support", "I agree")
    timeline = await storage.get_timeline(mid)
    assert len(timeline) >= 2


# --- API-level tests ---

@pytest.mark.asyncio(loop_scope="session")
async def test_api_get_events(client_and_app):
    client, _ = client_and_app
    resp = await client.get("/api/v1/events")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio(loop_scope="session")
async def test_api_get_events_with_params(client_and_app):
    client, _ = client_and_app
    resp = await client.get("/api/v1/events", params={"type": "test", "limit": 5})
    assert resp.status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_api_events_stream_is_sse():
    """Verify SSE endpoint route is registered correctly."""
    from agora.coordinator.dashboard import router
    paths = [getattr(r, "path", "") for r in router.routes]
    assert "/events/stream" in paths


@pytest.mark.asyncio(loop_scope="session")
async def test_api_timeline_not_found(client_and_app):
    client, _ = client_and_app
    resp = await client.get("/api/v1/discussions/nonexistent/timeline")
    assert resp.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_api_dashboard_page_no_token(client_and_app):
    """No JWT → /dashboard should redirect to /login (Phase 15.A)."""
    client, _ = client_and_app
    resp = await client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers.get("location", "")


@pytest.mark.asyncio(loop_scope="session")
async def test_api_dashboard_page_with_valid_token(client_and_app):
    """Valid JWT via Bearer header → /dashboard should return 200."""
    client, app = client_and_app
    token_mgr = app.state.token_mgr
    token = token_mgr.create_token(
        agent_id="dashboard_user:testadmin", role="admin"
    )
    resp = await client.get(
        "/dashboard",
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
