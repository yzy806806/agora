"""Tests for workspace REST API bulk endpoints (Phase 14.3c)."""
from __future__ import annotations

import base64
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
from agora.coordinator.workspace.workspace_router_bulk import (
    router_bulk as ws_router_bulk,
)

ATOK = "ag-testtoken123456"
AUTH_HDRS = {"Authorization": "Bearer " + ATOK}


@pytest.fixture
def ws_env():
    """Create temp DB + local backend + WorkspaceManager."""
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "test.db")
    backend = LocalFileBackend(root=os.path.join(tmp, "ws"))
    import aiosqlite
    import asyncio

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
                    UNIQUE(project_id, path)
                );
                CREATE TABLE IF NOT EXISTS file_locks (
                    id TEXT PRIMARY KEY, file_id TEXT NOT NULL,
                    project_id TEXT NOT NULL, path TEXT NOT NULL,
                    lock_type TEXT NOT NULL DEFAULT 'write',
                    held_by TEXT NOT NULL, acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY (file_id) REFERENCES file_nodes(id)
                );
            """)
            await db.commit()
    asyncio.get_event_loop().run_until_complete(_init())
    mgr = WorkspaceManager(db_path, backend)
    yield {"db_path": db_path, "backend": backend, "manager": mgr, "tmp": tmp}
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def client(ws_env):
    """FastAPI test client with all workspace routers."""
    app = FastAPI()
    app.include_router(ws_router)
    app.include_router(ws_router_read)
    app.include_router(ws_router_bulk)
    init_workspace_router_deps(ws_env["manager"])
    app.state.token_mgr = None
    return TestClient(app, raise_server_exceptions=False)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class TestBulkPull:
    def test_pull_existing_files(self, client):
        # Create two files first
        client.post("/workspaces/p1/files/a.txt",
                    content=b"aaa", headers=AUTH_HDRS)
        client.post("/workspaces/p1/files/b.txt",
                    content=b"bbb", headers=AUTH_HDRS)
        resp = client.post(
            "/workspaces/p1/pull",
            json={"paths": ["a.txt", "b.txt"]}, headers=AUTH_HDRS,
        )
        assert resp.status_code == 200
        data = resp.json()["files"]
        assert base64.b64decode(data["a.txt"]) == b"aaa"
        assert base64.b64decode(data["b.txt"]) == b"bbb"

    def test_pull_skips_missing(self, client):
        client.post("/workspaces/p1/files/exists.txt",
                    content=b"yes", headers=AUTH_HDRS)
        resp = client.post(
            "/workspaces/p1/pull",
            json={"paths": ["exists.txt", "nope.txt"]}, headers=AUTH_HDRS,
        )
        assert resp.status_code == 200
        data = resp.json()["files"]
        assert "exists.txt" in data
        assert "nope.txt" not in data

    def test_pull_empty_paths_rejected(self, client):
        resp = client.post(
            "/workspaces/p1/pull",
            json={"paths": []}, headers=AUTH_HDRS,
        )
        assert resp.status_code == 422


class TestBulkPush:
    def test_push_creates_files(self, client):
        resp = client.post(
            "/workspaces/p1/push",
            json={
                "files": {
                    "x.txt": {"content_b64": _b64(b"xxx")},
                    "y.txt": {"content_b64": _b64(b"yyy")},
                },
            },
            headers=AUTH_HDRS,
        )
        assert resp.status_code == 200
        nodes = resp.json()["files"]
        assert len(nodes) == 2
        # Verify files exist via read
        r = client.get("/workspaces/p1/files/x.txt", headers=AUTH_HDRS)
        assert r.content == b"xxx"

    def test_push_with_lock_ids(self, client):
        resp = client.post(
            "/workspaces/p1/push",
            json={
                "files": {"z.txt": {"content_b64": _b64(b"zzz")}},
                "lock_ids": {"z.txt": "lock-abc"},
            },
            headers=AUTH_HDRS,
        )
        assert resp.status_code == 200
        assert len(resp.json()["files"]) == 1

    def test_push_empty_files_rejected(self, client):
        resp = client.post(
            "/workspaces/p1/push",
            json={"files": {}}, headers=AUTH_HDRS,
        )
        assert resp.status_code == 422
