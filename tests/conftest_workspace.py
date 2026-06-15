"""Shared fixtures for workspace manager tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import aiosqlite
import pytest

from agora.coordinator.workspace import (
    LocalFileBackend, WorkspaceManager,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS file_nodes (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, path TEXT NOT NULL,
    name TEXT NOT NULL, file_type TEXT NOT NULL DEFAULT 'file',
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
    FOREIGN KEY (file_id) REFERENCES file_nodes(id) ON DELETE CASCADE
);
"""


@pytest.fixture
async def mgr(tmp_path):
    """Create a WorkspaceManager with temp DB + local backend."""
    db_path = str(tmp_path / "test.db")
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()
    backend = LocalFileBackend(root=str(tmp_path / "ws"))
    return WorkspaceManager(db_path, backend)
