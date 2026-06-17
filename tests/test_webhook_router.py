"""Tests for webhook CRUD + trigger endpoint (Phase 14+ Part D)."""
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from agora.coordinator.main import create_app
from agora.coordinator.webhook_router import init_webhook_router_deps
from agora.coordinator.webhook_trigger import init_webhook_trigger_deps
from agora.coordinator.storage import Storage
from agora.coordinator.webhook_rate_limiter import WebhookRateLimiter
from agora.coordinator.webhook_verifier import compute_signature

# min 32 chars per WebhookRegisterRequest
SECRET = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


@pytest_asyncio.fixture(loop_scope="session")
async def client(tmp_path):
    db_path = str(tmp_path / "webhook_test.db")
    storage = Storage(db_path)
    await storage.init_db()
    limiter = WebhookRateLimiter()
    init_webhook_router_deps(storage)
    init_webhook_trigger_deps(storage, limiter)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, storage


def _create_body(**overrides):
    body = {
        "project_id": "proj1", "name": "test-hook",
        "secret": SECRET,
        "pipeline_template": '{"idea": "test"}',
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
async def test_create_webhook_no_secret(client):
    c, _ = client
    body = _create_body()
    del body["secret"]
    resp = await c.post("/api/v1/webhooks", json=body)
    assert resp.status_code == 422


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


# ── D.3: Trigger + HMAC verification tests ────────────────

@pytest.mark.asyncio
async def test_trigger_webhook_valid_sig(client):
    c, _ = client
    created = await c.post(
        "/api/v1/webhooks", json=_create_body(secret=SECRET))
    wh_id = created.json()["id"]
    body = b'{"event":"push"}'
    ts = str(int(time.time()))
    sig = compute_signature(SECRET, body)
    resp = await c.post(
        f"/api/v1/webhooks/{wh_id}/trigger",
        content=body,
        headers={
            "x-agora-signature-256": sig,
            "x-agora-timestamp": ts,
            "content-type": "application/json",
        })
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_trigger_webhook_bad_signature(client):
    c, _ = client
    created = await c.post(
        "/api/v1/webhooks", json=_create_body(secret=SECRET))
    wh_id = created.json()["id"]
    resp = await c.post(
        f"/api/v1/webhooks/{wh_id}/trigger",
        content=b'{"event":"push"}',
        headers={
            "x-agora-signature-256": "sha256=badhex",
            "x-agora-timestamp": str(int(time.time())),
            "content-type": "application/json",
        })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_trigger_webhook_missing_sig(client):
    c, _ = client
    created = await c.post(
        "/api/v1/webhooks", json=_create_body(secret=SECRET))
    wh_id = created.json()["id"]
    resp = await c.post(
        f"/api/v1/webhooks/{wh_id}/trigger",
        json={"event": "push"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_trigger_webhook_expired_timestamp(client):
    c, _ = client
    created = await c.post(
        "/api/v1/webhooks", json=_create_body(secret=SECRET))
    wh_id = created.json()["id"]
    body = b'{"event":"push"}'
    ts = str(int(time.time() - 600))  # 10 min ago
    sig = compute_signature(SECRET, body)
    resp = await c.post(
        f"/api/v1/webhooks/{wh_id}/trigger",
        content=body,
        headers={
            "x-agora-signature-256": sig,
            "x-agora-timestamp": ts,
            "content-type": "application/json",
        })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_trigger_history(client):
    c, _ = client
    created = await c.post(
        "/api/v1/webhooks", json=_create_body(secret=SECRET))
    wh_id = created.json()["id"]
    body = b'{"event":"push"}'
    ts = str(int(time.time()))
    sig = compute_signature(SECRET, body)
    await c.post(
        f"/api/v1/webhooks/{wh_id}/trigger",
        content=body,
        headers={
            "x-agora-signature-256": sig,
            "x-agora-timestamp": ts,
            "content-type": "application/json",
        })
    resp = await c.get(f"/api/v1/webhooks/{wh_id}/history")
    assert resp.status_code == 200
    assert len(resp.json()["history"]) == 1
