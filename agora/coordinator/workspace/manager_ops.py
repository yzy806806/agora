"""WorkspaceManager — read, delete, stat, and locking operations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

import aiosqlite

from .backend import StorageBackend
from .models import FileNode, FileLock, LockType

logger = logging.getLogger(__name__)


class WorkspaceManagerOps:
    """Mixin-style class for read/delete/stat/lock ops.

    Composed by WorkspaceManager; kept separate to stay under 80 lines.
    """

    def __init__(self, db_path: str, backend: StorageBackend) -> None:
        self.db_path = db_path
        self.backend = backend

    @property
    def _conn(self):
        return aiosqlite.connect(self.db_path)

    def _parse_node(self, row: aiosqlite.Row) -> FileNode:
        return FileNode(**dict(row))

    async def _get_node(
        self, db: aiosqlite.Connection, project_id: str, path: str,
    ) -> FileNode | None:
        cur = await db.execute(
            "SELECT * FROM file_nodes WHERE project_id=? AND path=?",
            [project_id, path],
        )
        row = await cur.fetchone()
        return self._parse_node(row) if row else None

    async def read_file(
        self, project_id: str, path: str, agent_id: str,
    ) -> tuple[FileNode, bytes]:
        """Read file metadata + content. Always allowed (no lock check)."""
        content = await self.backend.get(project_id, path)
        if content is None:
            msg = f"File not found: {project_id}/{path}"
            raise FileNotFoundError(msg)
        async with self._conn as db:
            db.row_factory = aiosqlite.Row
            node = await self._get_node(db, project_id, path)
        if node is None:
            msg = f"File metadata not found: {project_id}/{path}"
            raise FileNotFoundError(msg)
        return node, content

    async def read_file_range(
        self, project_id: str, path: str,
        offset: int, length: int, agent_id: str,
    ) -> bytes:
        """Read a byte range (streaming support)."""
        return await self.backend.get_range(project_id, path, offset, length)

    async def delete_file(
        self, project_id: str, path: str, agent_id: str,
    ) -> bool:
        """Delete a file. Fails if locked by another agent."""
        async with self._conn as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM file_locks WHERE project_id=? AND path=?"
                " AND held_by!=?",
                [project_id, path, agent_id],
            )
            if await cur.fetchone():
                msg = f"File locked by another agent: {path}"
                raise PermissionError(msg)
            node = await self._get_node(db, project_id, path)
            if node is None:
                return False
            await db.execute(
                "DELETE FROM file_nodes WHERE id=?", [node.id])
            await db.commit()
        await self.backend.delete(project_id, path)
        return True

    async def stat(
        self, project_id: str, path: str,
    ) -> FileNode | None:
        """Get file metadata without content."""
        async with self._conn as db:
            db.row_factory = aiosqlite.Row
            return await self._get_node(db, project_id, path)
