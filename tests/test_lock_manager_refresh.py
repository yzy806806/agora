"""Tests for LockManager: refresh, acquire-with-expiry, integration."""
import pytest
from datetime import datetime, timezone, timedelta

from agora.coordinator.workspace.lock_manager import LockManager
from agora.coordinator.workspace.models import LockType


@pytest.fixture
async def lm(tmp_path):
    import aiosqlite
    db_path = str(tmp_path / "locks.db")
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


# ── refresh_lock ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_lock_extends_ttl(lm):
    lock = await lm.acquire_lock("p1", "a.txt", "a1", LockType.WRITE, ttl_seconds=10)
    old_expiry = lock.expires_at
    refreshed = await lm.refresh_lock(lock.id, "a1", ttl_seconds=600)
    assert refreshed.expires_at > old_expiry


@pytest.mark.asyncio
async def test_refresh_lock_wrong_agent(lm):
    lock = await lm.acquire_lock("p1", "a.txt", "a1", LockType.WRITE)
    with pytest.raises(PermissionError, match="not held by"):
        await lm.refresh_lock(lock.id, "a2", ttl_seconds=600)


@pytest.mark.asyncio
async def test_refresh_lock_nonexistent(lm):
    with pytest.raises(PermissionError):
        await lm.refresh_lock("nonexistent", "a1", ttl_seconds=600)


# ── acquire_lock auto-cleans expired ────────────────────────

@pytest.mark.asyncio
async def test_acquire_lock_skips_expired(lm):
    """An expired lock should not block a new acquire."""
    now = datetime.now(timezone.utc)
    # Manually insert an expired write lock
    async with lm._conn as db:
        await db.execute(
            "INSERT INTO file_locks VALUES(?,?,?,?,?,?,?,?)",
            ["l1", "f1", "p1", "a.txt", "write", "a1",
             now.isoformat(), (now - timedelta(seconds=1)).isoformat()],
        )
        await db.commit()
    # New agent should be able to acquire
    lock = await lm.acquire_lock("p1", "a.txt", "a2", LockType.WRITE)
    assert lock.held_by == "a2"


@pytest.mark.asyncio
async def test_acquire_lock_blocked_by_live(lm):
    """A live lock should still block new acquires."""
    await lm.acquire_lock("p1", "a.txt", "a1", LockType.WRITE, ttl_seconds=300)
    with pytest.raises(PermissionError, match="Lock conflict"):
        await lm.acquire_lock("p1", "a.txt", "a2", LockType.WRITE)


# ── check_lock skips expired ────────────────────────────────

@pytest.mark.asyncio
async def test_check_lock_returns_none_for_expired(lm):
    now = datetime.now(timezone.utc)
    async with lm._conn as db:
        await db.execute(
            "INSERT INTO file_locks VALUES(?,?,?,?,?,?,?,?)",
            ["l1", "f1", "p1", "a.txt", "write", "a1",
             now.isoformat(), (now - timedelta(seconds=1)).isoformat()],
        )
        await db.commit()
    assert await lm.check_lock("p1", "a.txt") is None


# ── check_lock_expired ──────────────────────────────────────

@pytest.mark.asyncio
async def test_check_lock_expired_true(lm):
    now = datetime.now(timezone.utc)
    async with lm._conn as db:
        await db.execute(
            "INSERT INTO file_locks VALUES(?,?,?,?,?,?,?,?)",
            ["l1", "f1", "p1", "a.txt", "write", "a1",
             now.isoformat(), (now - timedelta(seconds=1)).isoformat()],
        )
        await db.commit()
    assert await lm.check_lock_expired("p1", "a.txt", "a1") is True


@pytest.mark.asyncio
async def test_check_lock_expired_false_when_live(lm):
    await lm.acquire_lock("p1", "a.txt", "a1", LockType.WRITE, ttl_seconds=300)
    assert await lm.check_lock_expired("p1", "a.txt", "a1") is False


@pytest.mark.asyncio
async def test_check_lock_expired_false_when_no_lock(lm):
    assert await lm.check_lock_expired("p1", "a.txt", "a1") is False
