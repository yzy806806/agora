"""Tests for workspace REST API file endpoints (Phase 14.3a)."""
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
                    held_by TEXT NOT NULL,
                    acquired_at TEXT NOT NULL, expires_at TEXT NOT NULL,
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
    """FastAPI test client with workspace routers."""
    app = FastAPI()
    app.include_router(ws_router)
    app.include_router(ws_router_read)
    init_workspace_router_deps(ws_env["manager"])
    app.state.token_mgr = None
    return TestClient(app, raise_server_exceptions=False)


class TestWriteFile:
    def test_create_file(self, client):
        resp = client.post(
            "/workspaces/proj1/files/src/main.py",
            content=b"print('hello')",
            headers={**AUTH_HDRS, "Content-Type": "text/x-python"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["path"] == "src/main.py"
        assert data["size"] == 14
        assert data["version"] == 1

    def test_overwrite_file(self, client):
        # Create
        client.post(
            "/workspaces/proj1/files/readme.md",
            content=b"v1", headers=AUTH_HDRS,
        )
        # Overwrite
        resp = client.post(
            "/workspaces/proj1/files/readme.md",
            content=b"v2 updated", headers=AUTH_HDRS,
        )
        assert resp.status_code == 201
        assert resp.json()["version"] == 2
        assert resp.json()["size"] == 10


class TestReadFile:
    def test_read_existing(self, client):
        client.post(
            "/workspaces/proj1/files/hello.txt",
            content=b"hello world", headers=AUTH_HDRS,
        )
        resp = client.get(
            "/workspaces/proj1/files/hello.txt", headers=AUTH_HDRS,
        )
        assert resp.status_code == 200
        assert resp.content == b"hello world"
        assert "X-Checksum-SHA256" in resp.headers
        assert resp.headers["X-Version"] == "1"

    def test_read_not_found(self, client):
        resp = client.get(
            "/workspaces/proj1/files/nope.txt", headers=AUTH_HDRS,
        )
        assert resp.status_code == 404

    def test_read_with_range(self, client):
        client.post(
            "/workspaces/proj1/files/big.bin",
            content=b"0123456789abcdef", headers=AUTH_HDRS,
        )
        resp = client.get(
            "/workspaces/proj1/files/big.bin",
            headers={**AUTH_HDRS, "Range": "bytes=0-3"},
        )
        assert resp.status_code == 206
        assert resp.content == b"0123"
        assert "Content-Range" in resp.headers


class TestDeleteFile:
    def test_delete_existing(self, client):
        client.post(
            "/workspaces/proj1/files/del.txt",
            content=b"bye", headers=AUTH_HDRS,
        )
        resp = client.delete(
            "/workspaces/proj1/files/del.txt", headers=AUTH_HDRS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_delete_not_found(self, client):
        resp = client.delete(
            "/workspaces/proj1/files/ghost.txt", headers=AUTH_HDRS,
        )
        assert resp.status_code == 404


class TestStatFile:
    def test_stat_existing(self, client):
        client.post(
            "/workspaces/proj1/files/stat.txt",
            content=b"statme", headers=AUTH_HDRS,
        )
        resp = client.head(
            "/workspaces/proj1/files/stat.txt", headers=AUTH_HDRS,
        )
        assert resp.status_code == 200
        assert resp.headers["X-Size"] == "6"
        assert "X-Checksum-SHA256" in resp.headers
        assert resp.headers["X-Version"] == "1"

    def test_stat_not_found(self, client):
        resp = client.head(
            "/workspaces/proj1/files/nostat.txt", headers=AUTH_HDRS,
        )
        assert resp.status_code == 404
