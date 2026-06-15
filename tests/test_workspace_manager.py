"""Tests for WorkspaceManager file CRUD + lock operations."""
import pytest
import aiosqlite
from agora.coordinator.storage import Storage
from agora.coordinator.storage.schema import MIGRATION_14_TO_15
from agora.coordinator.workspace import WorkspaceManager, LocalFileBackend


@pytest.fixture
async def workspace(tmp_path):
    """Create a WorkspaceManager with temp DB + local backend."""
    db_path = str(tmp_path / "ws.db")
    backend = LocalFileBackend(root=str(tmp_path / "files"))
    # Initialize schema
    storage = Storage(db_path)
    await storage.init_db()
    return WorkspaceManager(db_path, backend)


@pytest.mark.asyncio
async def test_write_file_creates_node(workspace, tmp_path):
    node = await workspace.write_file(
        "proj1", "src/main.py", b"hello", "agent-1")
    assert node.project_id == "proj1"
    assert node.path == "src/main.py"
    assert node.name == "main.py"
    assert node.parent_path == "src"
    assert node.size == 5
    assert node.version == 1
    assert node.created_by == "agent-1"
    # Content on disk
    content = await workspace.backend.get("proj1", "src/main.py")
    assert content == b"hello"


@pytest.mark.asyncio
async def test_write_file_updates_existing(workspace):
    await workspace.write_file("p1", "a.txt", b"v1", "a1")
    node = await workspace.write_file("p1", "a.txt", b"v2-longer", "a2")
    assert node.version == 2
    assert node.size == 9
    _, content = await workspace.read_file("p1", "a.txt", "a1")
    assert content == b"v2-longer"


@pytest.mark.asyncio
async def test_read_file(workspace):
    await workspace.write_file("p1", "f.txt", b"data", "a1")
    node, content = await workspace.read_file("p1", "f.txt", "a1")
    assert node.path == "f.txt"
    assert content == b"data"


@pytest.mark.asyncio
async def test_read_file_not_found(workspace):
    with pytest.raises(FileNotFoundError):
        await workspace.read_file("p1", "missing.txt", "a1")


@pytest.mark.asyncio
async def test_delete_file(workspace):
    await workspace.write_file("p1", "d.txt", b"bye", "a1")
    assert await workspace.delete_file("p1", "d.txt", "a1") is True
    assert await workspace.stat("p1", "d.txt") is None


@pytest.mark.asyncio
async def test_delete_file_not_found(workspace):
    assert await workspace.delete_file("p1", "nope.txt", "a1") is False


@pytest.mark.asyncio
async def test_stat(workspace):
    await workspace.write_file("p1", "s.txt", b"stat", "a1")
    node = await workspace.stat("p1", "s.txt")
    assert node is not None
    assert node.path == "s.txt"
    assert await workspace.stat("p1", "nope") is None
