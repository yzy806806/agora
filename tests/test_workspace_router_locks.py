"""Tests for workspace REST API lock endpoints (Phase 14.3b)."""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agora.coordinator.workspace.local_backend import LocalFileBackend
from agora.coordinator.workspace.manager import WorkspaceManager
from agora.coordinator.workspace.workspace_router import (
    init_workspace_router_deps, router as ws_router,
)
from agora.coordinator.workspace.workspace_router_read import (
    router_read as ws_router_read,
)
from agora.coordinator.workspace.workspace_router_locks import (
    router_locks as ws_router_locks,
)

ATOK = "ag-testtoken123456"
AUTH = {"Authorization": "Bearer " + ATOK}


@pytest.fixture
def ws_env():
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "test.db")
    backend = LocalFileBackend(root=os.path.join(tmp, "ws"))
    import aiosqlite, asyncio

    async def _init():
        async with aiosqlite.connect(db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS file_nodes (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    path TEXT NOT NULL, name TEXT NOT NULL,
                    file_type TEXT NOT NULL DEFAULT 'file',
                    parent_path TEXT, size INTEGER NOT NULL DEFAULT 0,
                    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                    checksum_sha256 TEXT, created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(project_id, path));
                CREATE TABLE IF NOT EXISTS file_locks (
                    id TEXT PRIMARY KEY, file_id TEXT NOT NULL,
                    project_id TEXT NOT NULL, path TEXT NOT NULL,
                    lock_type TEXT NOT NULL DEFAULT 'write',
                    held_by TEXT NOT NULL, acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY (file_id) REFERENCES file_nodes(id));
            """)
            await db.commit()
    asyncio.get_event_loop().run_until_complete(_init())
    mgr = WorkspaceManager(db_path, backend)
    yield {"db_path": db_path, "manager": mgr, "tmp": tmp}
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def client(ws_env):
    app = FastAPI()
    app.include_router(ws_router)
    app.include_router(ws_router_read)
    app.include_router(ws_router_locks)
    init_workspace_router_deps(ws_env["manager"])
    app.state.token_mgr = None
    return TestClient(app, raise_server_exceptions=False)


class TestAcquireLock:
    def test_acquire_write_lock(self, client):
        client.post("/workspaces/p1/files/a.txt",
                     content=b"hi", headers=AUTH)
        resp = client.post("/workspaces/p1/locks", json={
            "path": "a.txt", "lock_type": "write",
            "agent_id": "agent-1", "ttl_seconds": 300,
        }, headers=AUTH)
        assert resp.status_code == 201
        data = resp.json()
        assert data["lock_type"] == "write"
        assert data["held_by"] == "agent-1"

    def test_lock_conflict(self, client):
        client.post("/workspaces/p1/files/b.txt",
                     content=b"hi", headers=AUTH)
        client.post("/workspaces/p1/locks", json={
            "path": "b.txt", "lock_type": "write",
            "agent_id": "agent-1",
        }, headers=AUTH)
        resp = client.post("/workspaces/p1/locks", json={
            "path": "b.txt", "lock_type": "write",
            "agent_id": "agent-2",
        }, headers=AUTH)
        assert resp.status_code == 409


class TestReleaseLock:
    def test_release_own_lock(self, client):
        client.post("/workspaces/p1/files/c.txt",
                     content=b"hi", headers=AUTH)
        r = client.post("/workspaces/p1/locks", json={
            "path": "c.txt", "lock_type": "write",
            "agent_id": "agent-1",
        }, headers=AUTH)
        lock_id = r.json()["id"]
        resp = client.delete(
            f"/workspaces/p1/locks/{lock_id}?agent_id=agent-1",
            headers=AUTH)
        assert resp.status_code == 200


class TestCheckLock:
    def test_check_unlocked(self, client):
        resp = client.get("/workspaces/p1/locks?path=x.txt", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["locked"] is False

    def test_check_locked(self, client):
        client.post("/workspaces/p1/files/d.txt",
                     content=b"hi", headers=AUTH)
        client.post("/workspaces/p1/locks", json={
            "path": "d.txt", "lock_type": "read",
            "agent_id": "agent-1",
        }, headers=AUTH)
        resp = client.get("/workspaces/p1/locks?path=d.txt", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["locked"] is True
