"""WorkspaceManager - read, delete, stat, list_dir, pull, push methods.

Mixed into WorkspaceManager via multiple inheritance to keep each file <=80 lines.
"""
from __future__ import annotations

import logging

import aiosqlite

from .manager_base import WorkspaceManagerBase
from .manager_dirs import WorkspaceManagerDirOps
from .models import FileNode
from .ws_messages import emit_file_deleted

logger = logging.getLogger(__name__)


class WorkspaceManagerReadOps(WorkspaceManagerDirOps):
    """Read, delete, stat, list_dir, pull, push operations."""

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
        """Delete a file. Fails if locked by another, or own lock expired."""
        async with self._conn as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM file_locks WHERE project_id=? AND path=?"
                " AND held_by!=?", [project_id, path, agent_id],
            )
            if await cur.fetchone():
                msg = f"File locked by another agent: {path}"
                raise PermissionError(msg)
            if await self.locks.check_lock_expired(project_id, path, agent_id):
                msg = f"Lock expired on {path}, must re-acquire"
                raise PermissionError(msg)
            node = await self._get_node(db, project_id, path)
            if node is None:
                return False
            await db.execute("DELETE FROM file_nodes WHERE id=?", [node.id])
            await db.commit()
        await self.backend.delete(project_id, path)
        # Emit WS event after successful delete
        await emit_file_deleted(project_id, path, agent_id)
        return True

    async def stat(self, project_id: str, path: str) -> FileNode | None:
        """Get file metadata without content."""
        async with self._conn as db:
            db.row_factory = aiosqlite.Row
            return await self._get_node(db, project_id, path)

    async def list_dir(
        self, project_id: str, path: str = "", recursive: bool = False,
    ) -> list[FileNode]:
        """List directory contents."""
        async with self._conn as db:
            db.row_factory = aiosqlite.Row
            if recursive:
                prefix = f"{path}/" if path else ""
                cur = await db.execute(
                    "SELECT * FROM file_nodes WHERE project_id=? AND "
                    "(parent_path=? OR parent_path LIKE ?)",
                    [project_id, path, f"{prefix}%"],
                )
            else:
                cur = await db.execute(
                    "SELECT * FROM file_nodes WHERE project_id=? AND "
                    "parent_path=?", [project_id, path],
                )
            rows = await cur.fetchall()
        return [self._parse_node(r) for r in rows]

    async def pull(
        self, project_id: str, paths: list[str], agent_id: str,
    ) -> dict[str, bytes]:
        """Bulk read multiple files (for task bootstrap)."""
        result: dict[str, bytes] = {}
        for p in paths:
            _, content = await self.read_file(project_id, p, agent_id)
            result[p] = content
        return result

    async def push(
        self, project_id: str, files: dict[str, bytes], agent_id: str,
    ) -> list[FileNode]:
        """Bulk write multiple files (for task completion)."""
        nodes: list[FileNode] = []
        for p, content in files.items():
            node = await self.write_file(project_id, p, content, agent_id)
            nodes.append(node)
        return nodes
