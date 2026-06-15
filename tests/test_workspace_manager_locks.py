"""Tests for WorkspaceManager locking + bulk operations."""
import pytest
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
async def test_acquire_write_lock(workspace):
    await workspace.write_file("p1", "f.txt", b"x", "a1")
    lock = await workspace.locks.acquire_lock(
        "p1", "f.txt", "a1", LockType.WRITE)
    assert lock.lock_type == LockType.WRITE
    assert lock.held_by == "a1"


@pytest.mark.asyncio
async def test_write_blocked_by_another_lock(workspace):
    await workspace.write_file("p1", "f.txt", b"x", "a1")
    await workspace.locks.acquire_lock("p1", "f.txt", "a1", LockType.WRITE)
    with pytest.raises(PermissionError):
        await workspace.write_file("p1", "f.txt", b"y", "a2")


@pytest.mark.asyncio
async def test_write_blocked_by_read_lock(workspace):
    """READ lock must block writes from other agents (C.2 matrix)."""
    await workspace.write_file("p1", "f.txt", b"x", "a1")
    await workspace.locks.acquire_lock("p1", "f.txt", "a1", LockType.READ)
    with pytest.raises(PermissionError):
        await workspace.write_file("p1", "f.txt", b"y", "a2")


@pytest.mark.asyncio
async def test_delete_blocked_by_another_lock(workspace):
    await workspace.write_file("p1", "f.txt", b"x", "a1")
    await workspace.locks.acquire_lock("p1", "f.txt", "a1", LockType.WRITE)
    with pytest.raises(PermissionError):
        await workspace.delete_file("p1", "f.txt", "a2")


@pytest.mark.asyncio
async def test_release_lock(workspace):
    await workspace.write_file("p1", "f.txt", b"x", "a1")
    lock = await workspace.locks.acquire_lock(
        "p1", "f.txt", "a1", LockType.WRITE)
    assert await workspace.locks.release_lock(lock.id, "a1") is True
    # Now another agent can write
    await workspace.write_file("p1", "f.txt", b"y", "a2")


@pytest.mark.asyncio
async def test_check_lock(workspace):
    await workspace.write_file("p1", "f.txt", b"x", "a1")
    assert await workspace.locks.check_lock("p1", "f.txt") is None
    lock = await workspace.locks.acquire_lock(
        "p1", "f.txt", "a1", LockType.READ)
    found = await workspace.locks.check_lock("p1", "f.txt")
    assert found is not None
    assert found.id == lock.id


@pytest.mark.asyncio
async def test_pull_push(workspace):
    await workspace.write_file("p1", "a.txt", b"aa", "a1")
    await workspace.write_file("p1", "b.txt", b"bb", "a1")
    data = await workspace.pull("p1", ["a.txt", "b.txt"], "a1")
    assert data == {"a.txt": b"aa", "b.txt": b"bb"}
    nodes = await workspace.push("p1", {"c.txt": b"cc"}, "a1")
    assert len(nodes) == 1
    assert nodes[0].path == "c.txt"
