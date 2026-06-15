"""Tests for workspace REST API dir endpoints (Phase 14.3b)."""
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
from agora.coordinator.workspace.workspace_router_dirs import (
    router_dirs as ws_router_dirs,
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
    app.include_router(ws_router_dirs)
    init_workspace_router_deps(ws_env["manager"])
    app.state.token_mgr = None
    return TestClient(app, raise_server_exceptions=False)


class TestMkdir:
    def test_create_dir(self, client):
        resp = client.post("/workspaces/proj1/dirs/src", headers=AUTH)
        assert resp.status_code == 201
        data = resp.json()
        assert data["path"] == "src"
        assert data["file_type"] == "directory"

    def test_mkdir_idempotent(self, client):
        client.post("/workspaces/proj1/dirs/src", headers=AUTH)
        resp = client.post("/workspaces/proj1/dirs/src", headers=AUTH)
        assert resp.status_code == 201
        assert resp.json()["path"] == "src"


class TestRmdir:
    def test_rmdir_empty(self, client):
        client.post("/workspaces/proj1/dirs/emptydir", headers=AUTH)
        resp = client.delete("/workspaces/proj1/dirs/emptydir", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

    def test_rmdir_not_found(self, client):
        resp = client.delete("/workspaces/proj1/dirs/nosuchdir", headers=AUTH)
        assert resp.status_code == 404

    def test_rmdir_not_empty(self, client):
        client.post("/workspaces/proj1/dirs/haschild", headers=AUTH)
        client.post("/workspaces/proj1/files/haschild/a.txt",
                     content=b"x", headers=AUTH)
        resp = client.delete("/workspaces/proj1/dirs/haschild", headers=AUTH)
        assert resp.status_code == 409


class TestListDir:
    def test_list_dir(self, client):
        client.post("/workspaces/proj1/dirs/src", headers=AUTH)
        client.post("/workspaces/proj1/files/src/main.py",
                     content=b"hi", headers=AUTH)
        resp = client.get("/workspaces/proj1/tree?path=src", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == "src"
        assert len(data["entries"]) >= 1
