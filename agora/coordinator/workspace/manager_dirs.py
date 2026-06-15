"""WorkspaceManager — mkdir / rmdir directory operations.

Mixed into WorkspaceManager via MRO to keep each file ≤80 lines.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiosqlite

from .manager_base import WorkspaceManagerBase
from .models import FileNode, FileType

logger = logging.getLogger(__name__)


class WorkspaceManagerDirOps(WorkspaceManagerBase):
    """Directory creation and removal operations."""

    async def mkdir(
        self, project_id: str, path: str, agent_id: str,
    ) -> FileNode:
        """Create a directory (idempotent — returns existing if present)."""
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        parent = path.rsplit("/", 1)[0] if "/" in path else None
        async with self._conn as db:
            db.row_factory = aiosqlite.Row
            existing = await self._get_node(db, project_id, path)
            if existing:
                return existing
            node = FileNode(
                project_id=project_id, path=path, name=name,
                file_type=FileType.DIRECTORY, parent_path=parent,
                size=0, created_by=agent_id,
            )
            await db.execute(
                "INSERT INTO file_nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [node.id, node.project_id, node.path, node.name,
                 node.file_type.value, node.parent_path, node.size,
                 node.content_type, node.checksum_sha256, node.created_by,
                 node.created_at.isoformat(), node.updated_at.isoformat(),
                 node.version],
            )
            await db.commit()
            return node

    async def rmdir(
        self, project_id: str, path: str, agent_id: str,
    ) -> bool:
        """Remove an empty directory. Fails if not empty or locked."""
        async with self._conn as db:
            db.row_factory = aiosqlite.Row
            node = await self._get_node(db, project_id, path)
            if node is None or node.file_type != FileType.DIRECTORY:
                return False
            # Check directory is empty (no children)
            cur = await db.execute(
                "SELECT id FROM file_nodes WHERE project_id=? "
                "AND parent_path=? LIMIT 1",
                [project_id, path],
            )
            if await cur.fetchone():
                msg = f"Directory not empty: {path}"
                raise ValueError(msg)
            # Check no locks on the directory itself
            cur = await db.execute(
                "SELECT * FROM file_locks WHERE project_id=? AND path=?"
                " AND held_by!=?", [project_id, path, agent_id],
            )
            if await cur.fetchone():
                msg = f"Directory locked by another agent: {path}"
                raise PermissionError(msg)
            await db.execute(
                "DELETE FROM file_nodes WHERE id=?", [node.id])
            await db.commit()
            return True
