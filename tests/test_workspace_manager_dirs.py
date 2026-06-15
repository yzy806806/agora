"""Tests for WorkspaceManager directory operations (mkdir / rmdir)."""
import pytest
from agora.coordinator.storage import Storage
from agora.coordinator.workspace import WorkspaceManager, LocalFileBackend
from agora.coordinator.workspace.models import LockType


@pytest.fixture
async def workspace(tmp_path):
    """Create a WorkspaceManager with temp DB + local backend."""
    db_path = str(tmp_path / "ws.db")
    backend = LocalFileBackend(root=str(tmp_path / "files"))
    storage = Storage(db_path)
    await storage.init_db()
    return WorkspaceManager(db_path, backend)


@pytest.mark.asyncio
async def test_mkdir_creates_directory(workspace):
    node = await workspace.mkdir("p1", "src", "agent-1")
    assert node.path == "src"
    assert node.name == "src"
    assert node.file_type.value == "directory"
    assert node.parent_path is None
    assert node.size == 0
    assert node.created_by == "agent-1"


@pytest.mark.asyncio
async def test_mkdir_nested(workspace):
    node = await workspace.mkdir("p1", "src/utils", "agent-1")
    assert node.path == "src/utils"
    assert node.name == "utils"
    assert node.parent_path == "src"
    assert node.file_type.value == "directory"


@pytest.mark.asyncio
async def test_mkdir_idempotent(workspace):
    n1 = await workspace.mkdir("p1", "docs", "a1")
    n2 = await workspace.mkdir("p1", "docs", "a2")
    assert n1.id == n2.id
    assert n2.created_by == "a1"  # original creator preserved


@pytest.mark.asyncio
async def test_rmdir_removes_empty_dir(workspace):
    await workspace.mkdir("p1", "empty", "a1")
    assert await workspace.rmdir("p1", "empty", "a1") is True
    assert await workspace.stat("p1", "empty") is None


@pytest.mark.asyncio
async def test_rmdir_not_a_directory(workspace):
    await workspace.write_file("p1", "file.txt", b"x", "a1")
    assert await workspace.rmdir("p1", "file.txt", "a1") is False


@pytest.mark.asyncio
async def test_rmdir_not_found(workspace):
    assert await workspace.rmdir("p1", "nope", "a1") is False


@pytest.mark.asyncio
async def test_rmdir_not_empty(workspace):
    await workspace.mkdir("p1", "src", "a1")
    await workspace.write_file("p1", "src/main.py", b"code", "a1")
    with pytest.raises(ValueError, match="not empty"):
        await workspace.rmdir("p1", "src", "a1")


@pytest.mark.asyncio
async def test_rmdir_locked_by_another(workspace):
    await workspace.mkdir("p1", "locked", "a1")
    # Lock the directory path
    await workspace.locks.acquire_lock("p1", "locked", "a1", LockType.WRITE)
    with pytest.raises(PermissionError, match="locked"):
        await workspace.rmdir("p1", "locked", "a2")


@pytest.mark.asyncio
async def test_list_dir_shows_directory(workspace):
    await workspace.mkdir("p1", "src", "a1")
    await workspace.write_file("p1", "src/main.py", b"hi", "a1")
    entries = await workspace.list_dir("p1", "src")
    paths = [e.path for e in entries]
    assert "src/main.py" in paths
