"""Tests for LockManager: expiry, refresh, cleanup, and edge cases."""
import pytest
from datetime import datetime, timezone, timedelta

from agora.coordinator.workspace.lock_manager import LockManager
from agora.coordinator.workspace.models import FileLock, LockType


@pytest.fixture
async def lm(tmp_path):
    """LockManager with a fresh SQLite DB."""
    import aiosqlite
    db_path = str(tmp_path / "locks.db")
    # Create the file_locks table
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE file_locks ("
            "id TEXT, file_id TEXT, project_id TEXT, path TEXT, "
            "lock_type TEXT, held_by TEXT, acquired_at TEXT, expires_at TEXT)"
        )
        await db.execute(
            "CREATE TABLE file_nodes ("
            "id TEXT, project_id TEXT, path TEXT, name TEXT, "
            "file_type TEXT, parent_path TEXT, size INTEGER, "
            "content_type TEXT, checksum_sha256 TEXT, created_by TEXT, "
            "created_at TEXT, updated_at TEXT, version INTEGER)"
        )
        await db.commit()
    return LockManager(db_path)


def _make_lock(**overrides) -> FileLock:
    """Build a FileLock with sensible defaults."""
    now = datetime.now(timezone.utc)
    defaults = dict(
        file_id="f1", project_id="p1", path="a.txt",
        lock_type=LockType.WRITE, held_by="agent1",
        acquired_at=now, expires_at=now + timedelta(seconds=300),
    )
    defaults.update(overrides)
    return FileLock(**defaults)


# ── is_expired ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_is_expired_false_for_future(lm):
    lock = _make_lock(expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    assert lm.is_expired(lock) is False


@pytest.mark.asyncio
async def test_is_expired_true_for_past(lm):
    lock = _make_lock(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert lm.is_expired(lock) is True


# ── cleanup_expired ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_cleanup_expired_removes_only_expired(lm):
    now = datetime.now(timezone.utc)
    # Insert one expired, one live lock
    async with lm._conn as db:
        await db.execute(
            "INSERT INTO file_locks VALUES(?,?,?,?,?,?,?,?)",
            ["l1", "f1", "p1", "a.txt", "write", "a1",
             now.isoformat(), (now - timedelta(seconds=1)).isoformat()],
        )
        await db.execute(
            "INSERT INTO file_locks VALUES(?,?,?,?,?,?,?,?)",
            ["l2", "f2", "p1", "b.txt", "write", "a2",
             now.isoformat(), (now + timedelta(hours=1)).isoformat()],
        )
        await db.commit()
    removed = await lm.cleanup_expired("p1")
    assert removed == 1
    # Live lock should still be there
    found = await lm.check_lock("p1", "b.txt")
    assert found is not None
    assert found.id == "l2"


@pytest.mark.asyncio
async def test_cleanup_expired_global(lm):
    now = datetime.now(timezone.utc)
    async with lm._conn as db:
        await db.execute(
            "INSERT INTO file_locks VALUES(?,?,?,?,?,?,?,?)",
            ["l1", "f1", "p1", "a.txt", "write", "a1",
             now.isoformat(), (now - timedelta(seconds=1)).isoformat()],
        )
        await db.execute(
            "INSERT INTO file_locks VALUES(?,?,?,?,?,?,?,?)",
            ["l2", "f2", "p2", "a.txt", "write", "a1",
             now.isoformat(), (now - timedelta(seconds=1)).isoformat()],
        )
        await db.commit()
    removed = await lm.cleanup_expired()
    assert removed == 2
