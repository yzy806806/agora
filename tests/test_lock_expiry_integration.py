"""Tests: write_file/delete_file reject when own lock expired."""
import pytest
from datetime import datetime, timezone, timedelta

from agora.coordinator.storage import Storage
from agora.coordinator.workspace import WorkspaceManager, LocalFileBackend
from agora.coordinator.workspace.models import LockType


@pytest.fixture
async def workspace(tmp_path):
    db_path = str(tmp_path / "ws.db")
    backend = LocalFileBackend(root=str(tmp_path / "files"))
    storage = Storage(db_path)
    await storage.init_db()
    return WorkspaceManager(db_path, backend)


@pytest.mark.asyncio
async def test_write_rejected_when_own_lock_expired(workspace):
    """Design J.1: write_file rejects if agent's own lock expired."""
    await workspace.write_file("p1", "f.txt", b"x", "a1")
    lock = await workspace.locks.acquire_lock(
        "p1", "f.txt", "a1", LockType.WRITE, ttl_seconds=1)
    # Manually expire the lock in DB
    now = datetime.now(timezone.utc)
    async with workspace.locks._conn as db:
        await db.execute(
            "UPDATE file_locks SET expires_at=? WHERE id=?",
            [(now - timedelta(seconds=1)).isoformat(), lock.id],
        )
        await db.commit()
    with pytest.raises(PermissionError, match="Lock expired"):
        await workspace.write_file("p1", "f.txt", b"y", "a1")


@pytest.mark.asyncio
async def test_delete_rejected_when_own_lock_expired(workspace):
    """Design J.1: delete_file rejects if agent's own lock expired."""
    await workspace.write_file("p1", "f.txt", b"x", "a1")
    lock = await workspace.locks.acquire_lock(
        "p1", "f.txt", "a1", LockType.WRITE, ttl_seconds=1)
    now = datetime.now(timezone.utc)
    async with workspace.locks._conn as db:
        await db.execute(
            "UPDATE file_locks SET expires_at=? WHERE id=?",
            [(now - timedelta(seconds=1)).isoformat(), lock.id],
        )
        await db.commit()
    with pytest.raises(PermissionError, match="Lock expired"):
        await workspace.delete_file("p1", "f.txt", "a1")


@pytest.mark.asyncio
async def test_write_succeeds_after_expired_lock_cleanup(workspace):
    """After cleanup, write should work (expired lock removed)."""
    await workspace.write_file("p1", "f.txt", b"x", "a1")
    now = datetime.now(timezone.utc)
    async with workspace.locks._conn as db:
        await db.execute(
            "INSERT INTO file_locks VALUES(?,?,?,?,?,?,?,?)",
            ["l1", "f1", "p1", "f.txt", "write", "a1",
             now.isoformat(), (now - timedelta(seconds=1)).isoformat()],
        )
        await db.commit()
    removed = await workspace.locks.cleanup_expired("p1")
    assert removed == 1
    # Now a2 can write (no lock blocks)
    await workspace.write_file("p1", "f.txt", b"y", "a2")


@pytest.mark.asyncio
async def test_refresh_keeps_write_allowed(workspace):
    """After refresh, the lock is still valid → write succeeds."""
    await workspace.write_file("p1", "f.txt", b"x", "a1")
    lock = await workspace.locks.acquire_lock(
        "p1", "f.txt", "a1", LockType.WRITE, ttl_seconds=300)
    await workspace.locks.refresh_lock(lock.id, "a1", ttl_seconds=600)
    # Write should still work
    node = await workspace.write_file("p1", "f.txt", b"y", "a1")
    assert node.version == 2
