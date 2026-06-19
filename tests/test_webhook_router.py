"""Tests for simplified webhook CRUD + trigger endpoint."""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from agora.coordinator.main import create_app
from agora.coordinator.webhook import init_webhook_router_deps
from agora.coordinator.webhook import init_webhook_trigger_deps
from agora.coordinator.storage import Storage


@pytest_asyncio.fixture(loop_scope="session")
async def client(tmp_path):
    db_path = str(tmp_path / "webhook_test.db")
    storage = Storage(db_path)
    await storage.init_db()
    init_webhook_router_deps(storage)
    init_webhook_trigger_deps(storage)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, storage


def _create_body(**overrides):
    body = {
        "project_id": "proj1", "name": "test-hook",
        "secret": "test-secret",
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_create_webhook(client):
    c, _ = client
    resp = await c.post("/api/v1/webhooks", json=_create_body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["name"] == "test-hook"
    assert data["project_id"] == "proj1"


@pytest.mark.asyncio
async def test_get_webhook(client):
    c, _ = client
    created = await c.post("/api/v1/webhooks", json=_create_body())
    wh_id = created.json()["id"]
    resp = await c.get(f"/api/v1/webhooks/{wh_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "test-hook"


@pytest.mark.asyncio
async def test_get_webhook_not_found(client):
    c, _ = client
    resp = await c.get("/api/v1/webhooks/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_webhook(client):
    c, _ = client
    created = await c.post("/api/v1/webhooks", json=_create_body())
    wh_id = created.json()["id"]
    resp = await c.put(
        f"/api/v1/webhooks/{wh_id}", json={"name": "updated"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "updated"


@pytest.mark.asyncio
async def test_delete_webhook(client):
    c, _ = client
    created = await c.post("/api/v1/webhooks", json=_create_body())
    wh_id = created.json()["id"]
    resp = await c.delete(f"/api/v1/webhooks/{wh_id}")
    assert resp.status_code == 200
    resp2 = await c.get(f"/api/v1/webhooks/{wh_id}")
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_trigger_webhook(client):
    c, _ = client
    created = await c.post(
        "/api/v1/webhooks", json=_create_body())
    wh_id = created.json()["id"]
    resp = await c.post(
        f"/api/v1/webhooks/{wh_id}/trigger",
        json={"event": "push"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_trigger_disabled_webhook(client):
    c, _ = client
    created = await c.post(
        "/api/v1/webhooks",
        json=_create_body(enabled=False))
    wh_id = created.json()["id"]
    resp = await c.post(
        f"/api/v1/webhooks/{wh_id}/trigger",
        json={"event": "push"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_trigger_history(client):
    c, _ = client
    created = await c.post(
        "/api/v1/webhooks", json=_create_body())
    wh_id = created.json()["id"]
    await c.post(
        f"/api/v1/webhooks/{wh_id}/trigger",
        json={"event": "push"})
    resp = await c.get(f"/api/v1/webhooks/{wh_id}/history")
    assert resp.status_code == 200
