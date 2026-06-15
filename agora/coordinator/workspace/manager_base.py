"""WorkspaceManager base — shared DB helpers for workspace operations."""

from __future__ import annotations

import aiosqlite

from .models import FileNode


class WorkspaceManagerBase:
    """Base with DB connection + node lookup helpers."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

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
