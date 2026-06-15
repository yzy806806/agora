"""WorkspaceManager — file write/create + lock check + MRO glue."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiosqlite

from .backend import StorageBackend
from .lock_manager import LockManager
from .manager_base import WorkspaceManagerBase
from .manager_bulk import WorkspaceManagerBulkOps
from .models import FileNode, FileType
from .ws_messages import emit_file_changed

logger = logging.getLogger(__name__)

class WorkspaceManager(WorkspaceManagerBulkOps):
    """Orchestrates file CRUD, directory ops, and locking.

    MRO: WorkspaceManager → BulkOps → ReadOps → DirOps → Base.
    Adds write_file + lock check here.
    """

    def __init__(self, db_path: str, backend: StorageBackend) -> None:
        super().__init__(db_path)
        self.backend = backend
        self.locks = LockManager(db_path)

    async def _check_write_lock(
        self, db: aiosqlite.Connection, project_id: str,
        path: str, agent_id: str,
    ) -> None:
        """Raise if file locked by another agent, or own lock expired."""
        cur = await db.execute(
            "SELECT * FROM file_locks WHERE project_id=? AND path=?"
            " AND lock_type IN ('write','read') AND held_by!=?",
            [project_id, path, agent_id],
        )
        if await cur.fetchone():
            msg = f"File locked by another agent: {path}"
            raise PermissionError(msg)
        # Check if agent's own lock has expired (design J.1)
        if await self.locks.check_lock_expired(project_id, path, agent_id):
            msg = f"Lock expired on {path}, must re-acquire"
            raise PermissionError(msg)

    async def write_file(
        self, project_id: str, path: str, content: bytes,
        agent_id: str, content_type: str = "application/octet-stream",
    ) -> FileNode:
        """Create or overwrite a file. Fails if locked by another."""
        checksum = await self.backend.put(
            project_id, path, content, content_type)
        now = datetime.now(timezone.utc).isoformat()
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        parent = path.rsplit("/", 1)[0] if "/" in path else None
        async with self._conn as db:
            db.row_factory = aiosqlite.Row
            await self._check_write_lock(db, project_id, path, agent_id)
            existing = await self._get_node(db, project_id, path)
            if existing:
                await db.execute(
                    "UPDATE file_nodes SET size=?, checksum_sha256=?, "
                    "updated_at=?, version=version+1, content_type=? "
                    "WHERE id=?",
                    [len(content), checksum, now, content_type, existing.id],
                )
                await db.commit()
                node = await self._get_node(db, project_id, path)
            else:
                node = FileNode(
                    project_id=project_id, path=path, name=name,
                    file_type=FileType.FILE, parent_path=parent,
                    size=len(content), content_type=content_type,
                    checksum_sha256=checksum, created_by=agent_id,
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
        # Emit WS event after successful write
        await emit_file_changed(
            project_id, path, agent_id, node.version)  # type: ignore
        return node  # type: ignore
