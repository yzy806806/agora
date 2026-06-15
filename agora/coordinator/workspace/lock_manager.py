"""LockManager — lock acquire / release / check / expiry / refresh."""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

import aiosqlite

from .models import FileLock, LockType
from .ws_messages import emit_lock_acquired, emit_lock_expired, emit_lock_released

logger = logging.getLogger(__name__)


class LockManager:
    """Manages file locks for workspace concurrency control."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    @property
    def _conn(self):
        return aiosqlite.connect(self.db_path)

    # ── expiry helpers ──────────────────────────────────────

    @staticmethod
    def is_expired(lock: FileLock) -> bool:
        """Return True if the lock's TTL has passed."""
        return datetime.now(timezone.utc) >= lock.expires_at

    async def cleanup_expired(
        self, project_id: str | None = None,
    ) -> int:
        """Delete all expired locks. Emit LOCK_EXPIRED per lock."""
        now = datetime.now(timezone.utc).isoformat()
        async with self._conn as db:
            db.row_factory = aiosqlite.Row
            # Fetch expired locks before deleting (for WS events)
            if project_id:
                cur = await db.execute(
                    "SELECT * FROM file_locks WHERE project_id=? "
                    "AND expires_at < ?", [project_id, now],
                )
            else:
                cur = await db.execute(
                    "SELECT * FROM file_locks WHERE expires_at < ?", [now],
                )
            expired_rows = await cur.fetchall()
            # Delete them
            if project_id:
                cur = await db.execute(
                    "DELETE FROM file_locks WHERE project_id=? "
                    "AND expires_at < ?", [project_id, now],
                )
            else:
                cur = await db.execute(
                    "DELETE FROM file_locks WHERE expires_at < ?", [now],
                )
            await db.commit()
        # Emit LOCK_EXPIRED for each expired lock
        for row in expired_rows:
            await emit_lock_expired(row["id"], row["path"], row["project_id"])
        return cur.rowcount

    async def refresh_lock(
        self, lock_id: str, agent_id: str, ttl_seconds: int = 300,
    ) -> FileLock:
        """Extend a lock's TTL. Raises if not found or wrong owner."""
        now = datetime.now(timezone.utc)
        new_expiry = now + timedelta(seconds=ttl_seconds)
        async with self._conn as db:
            cur = await db.execute(
                "SELECT * FROM file_locks WHERE id=? AND held_by=?",
                [lock_id, agent_id],
            )
            row = await cur.fetchone()
            if not row:
                msg = f"Lock {lock_id} not held by {agent_id}"
                raise PermissionError(msg)
            await db.execute(
                "UPDATE file_locks SET expires_at=? WHERE id=?",
                [new_expiry.isoformat(), lock_id],
            )
            await db.commit()
        return await self._get_lock(lock_id)  # type: ignore

    # ── core lock ops ───────────────────────────────────────

    async def acquire_lock(
        self, project_id: str, path: str, agent_id: str,
        lock_type: LockType, ttl_seconds: int = 300,
    ) -> FileLock:
        """Acquire a read or write lock. Skips expired, raises on live."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl_seconds)
        async with self._conn as db:
            db.row_factory = aiosqlite.Row
            # Purge expired locks for this path first
            await db.execute(
                "DELETE FROM file_locks WHERE project_id=? AND path=?"
                " AND expires_at < ?", [project_id, path, now.isoformat()],
            )
            await db.commit()
            # Check remaining (live) locks for conflict
            if lock_type == LockType.WRITE:
                cur = await db.execute(
                    "SELECT * FROM file_locks WHERE project_id=? AND path=?",
                    [project_id, path],
                )
            else:
                cur = await db.execute(
                    "SELECT * FROM file_locks WHERE project_id=? AND path=?"
                    " AND lock_type='write'",
                    [project_id, path],
                )
            conflict = await cur.fetchone()
            if conflict:
                msg = (f"Lock conflict: {lock_type.value} on {path} "
                       f"blocked by {conflict['lock_type']} held by "
                       f"{conflict['held_by']}")
                raise PermissionError(msg)
            # Find file_id (optional — lock can exist before file)
            cur = await db.execute(
                "SELECT id FROM file_nodes WHERE project_id=? AND path=?",
                [project_id, path],
            )
            row = await cur.fetchone()
            file_id = row["id"] if row else ""
            lock = FileLock(
                file_id=file_id, project_id=project_id, path=path,
                lock_type=lock_type, held_by=agent_id,
                acquired_at=now, expires_at=expires,
            )
            await db.execute(
                "INSERT INTO file_locks VALUES(?,?,?,?,?,?,?,?)",
                [lock.id, lock.file_id, lock.project_id, lock.path,
                 lock.lock_type.value, lock.held_by,
                 lock.acquired_at.isoformat(), lock.expires_at.isoformat()],
            )
            await db.commit()
        # Emit WS event after successful acquire
        await emit_lock_acquired(
            project_id, path, lock.lock_type.value, agent_id)
        return lock

    async def release_lock(self, lock_id: str, agent_id: str) -> bool:
        """Release a held lock. Returns True if released."""
        released_path: str | None = None
        async with self._conn as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM file_locks WHERE id=? AND held_by=?",
                [lock_id, agent_id],
            )
            row = await cur.fetchone()
            if not row:
                return False
            released_path = row["path"]
            project_id = row["project_id"]
            await db.execute("DELETE FROM file_locks WHERE id=?", [lock_id])
            await db.commit()
        # Emit WS event after successful release
        if released_path:
            await emit_lock_released(project_id, released_path, agent_id)
        return True

    async def check_lock(
        self, project_id: str, path: str,
    ) -> FileLock | None:
        """Check if a file has a live (non-expired) lock."""
        async with self._conn as db:
            db.row_factory = aiosqlite.Row
            now = datetime.now(timezone.utc).isoformat()
            cur = await db.execute(
                "SELECT * FROM file_locks WHERE project_id=? AND path=?"
                " AND expires_at >= ?", [project_id, path, now],
            )
            row = await cur.fetchone()
            if not row:
                return None
            return self._parse_lock(row)

    async def check_lock_expired(
        self, project_id: str, path: str, agent_id: str,
    ) -> bool:
        """Return True if agent's own lock on path has expired."""
        async with self._conn as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM file_locks WHERE project_id=? AND path=?"
                " AND held_by=?", [project_id, path, agent_id],
            )
            row = await cur.fetchone()
            if not row:
                return False  # no lock at all
            lock = self._parse_lock(row)
            return self.is_expired(lock)

    # ── internal helpers ────────────────────────────────────

    async def _get_lock(self, lock_id: str) -> FileLock | None:
        async with self._conn as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM file_locks WHERE id=?", [lock_id],
            )
            row = await cur.fetchone()
            if not row:
                return None
            return self._parse_lock(row)

    @staticmethod
    def _parse_lock(row: aiosqlite.Row) -> FileLock:
        d = dict(row)
        if isinstance(d.get("lock_type"), str):
            d["lock_type"] = LockType(d["lock_type"])
        return FileLock(**d)
