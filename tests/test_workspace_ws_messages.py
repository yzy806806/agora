"""Tests for workspace WS message events (Phase 14.4a).

Phase 16.10: Updated to work without init_ws_messages callback.
Now patches dashboard_hub.broadcast_event directly.
"""
import pytest
from unittest.mock import AsyncMock, patch
from agora.coordinator.storage import Storage
from agora.coordinator.workspace import (
    WorkspaceManager, LocalFileBackend,
)
from agora.coordinator.workspace.models import LockType
from agora.coordinator.models import MessageType


@pytest.fixture
def captured():
    """Collect broadcast messages in a list via dashboard_hub patch."""
    messages: list[dict] = []

    async def _broadcast_event(event_type, payload, channel="events"):
        messages.append({"type": event_type, "payload": payload})
        return 1

    with patch(
        "agora.coordinator.dashboard_ws.dashboard_hub.broadcast_event",
        new=_broadcast_event,
    ):
        yield messages


@pytest.fixture
async def workspace(tmp_path, captured):
    """Create a WorkspaceManager with temp DB + local backend."""
    db_path = str(tmp_path / "ws.db")
    backend = LocalFileBackend(root=str(tmp_path / "files"))
    storage = Storage(db_path)
    await storage.init_db()
    return WorkspaceManager(db_path, backend)


@pytest.mark.asyncio
async def test_file_created_event(workspace, captured):
    """write_file (new) emits WORKSPACE_FILE_CHANGED with version=1."""
    await workspace.write_file("p1", "src/main.py", b"hello", "a1")
    assert len(captured) == 1
    msg = captured[0]
    assert msg["type"] == MessageType.WORKSPACE_FILE_CHANGED
    assert msg["payload"]["project_id"] == "p1"
    assert msg["payload"]["path"] == "src/main.py"
    assert msg["payload"]["agent_id"] == "a1"
    assert msg["payload"]["version"] == 1


@pytest.mark.asyncio
async def test_file_updated_event(workspace, captured):
    """write_file (update) emits WORKSPACE_FILE_CHANGED with version=2."""
    await workspace.write_file("p1", "a.txt", b"v1", "a1")
    captured.clear()
    await workspace.write_file("p1", "a.txt", b"v2", "a2")
    assert len(captured) == 1
    msg = captured[0]
    assert msg["type"] == MessageType.WORKSPACE_FILE_CHANGED
    assert msg["payload"]["version"] == 2
    assert msg["payload"]["agent_id"] == "a2"


@pytest.mark.asyncio
async def test_file_deleted_event(workspace, captured):
    """delete_file emits WORKSPACE_FILE_CHANGED with action=deleted."""
    await workspace.write_file("p1", "f.txt", b"data", "a1")
    captured.clear()
    await workspace.delete_file("p1", "f.txt", "a1")
    assert len(captured) == 1
    msg = captured[0]
    assert msg["type"] == MessageType.WORKSPACE_FILE_CHANGED
    assert msg["payload"]["action"] == "deleted"
    assert msg["payload"]["path"] == "f.txt"


@pytest.mark.asyncio
async def test_lock_acquired_event(workspace, captured):
    """acquire_lock emits WORKSPACE_LOCK_ACQUIRED."""
    await workspace.write_file("p1", "f.txt", b"x", "a1")
    captured.clear()
    await workspace.locks.acquire_lock("p1", "f.txt", "a1", LockType.WRITE)
    assert len(captured) == 1
    msg = captured[0]
    assert msg["type"] == MessageType.WORKSPACE_LOCK_ACQUIRED
    assert msg["payload"]["lock_type"] == "write"
    assert msg["payload"]["held_by"] == "a1"
    assert msg["payload"]["path"] == "f.txt"


@pytest.mark.asyncio
async def test_lock_released_event(workspace, captured):
    """release_lock emits WORKSPACE_LOCK_RELEASED."""
    await workspace.write_file("p1", "f.txt", b"x", "a1")
    lock = await workspace.locks.acquire_lock(
        "p1", "f.txt", "a1", LockType.WRITE)
    captured.clear()
    await workspace.locks.release_lock(lock.id, "a1")
    assert len(captured) == 1
    msg = captured[0]
    assert msg["type"] == MessageType.WORKSPACE_LOCK_RELEASED
    assert msg["payload"]["path"] == "f.txt"
    assert msg["payload"]["held_by"] == "a1"


@pytest.mark.asyncio
async def test_lock_expired_event(workspace, captured):
    """cleanup_expired emits WORKSPACE_LOCK_EXPIRED per lock."""
    import asyncio
    await workspace.write_file("p1", "f.txt", b"x", "a1")
    await workspace.locks.acquire_lock(
        "p1", "f.txt", "a1", LockType.WRITE, ttl_seconds=0)
    captured.clear()
    await asyncio.sleep(0.05)
    count = await workspace.locks.cleanup_expired("p1")
    assert count >= 1
    expired_msgs = [
        m for m in captured
        if m["type"] == MessageType.WORKSPACE_LOCK_EXPIRED
    ]
    assert len(expired_msgs) >= 1
    assert expired_msgs[0]["payload"]["path"] == "f.txt"
