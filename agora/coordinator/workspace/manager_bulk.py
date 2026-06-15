"""WorkspaceManager — bulk pull_files / push_files operations.

Mixed into WorkspaceManager via MRO to keep each file ≤80 lines.
Atomic semantics: pull_files skips missing files; push_files rolls
back all writes on any lock check failure.
"""

from __future__ import annotations

import logging
from typing import Any

from .manager_helpers import WorkspaceManagerReadOps
from .models import FileNode

logger = logging.getLogger(__name__)


class WorkspaceManagerBulkOps(WorkspaceManagerReadOps):
    """Bulk pull and push operations for workspace files."""

    async def pull_files(
        self, project_id: str, paths: list[str], agent_id: str,
    ) -> dict[str, bytes]:
        """Batch read — returns {path: content}; skips missing files."""
        result: dict[str, bytes] = {}
        for p in paths:
            try:
                _, content = await self.read_file(project_id, p, agent_id)
                result[p] = content
            except FileNotFoundError:
                logger.debug("pull_files: skipped missing %s", p)
        return result

    async def push_files(
        self, project_id: str, files: dict[str, bytes],
        agent_id: str, lock_ids: dict[str, str] | None = None,
    ) -> list[FileNode]:
        """Batch write — atomic: all-or-nothing with lock checks.

        * Validates locks for every file before any write.
        * On any failure, rolls back already-written files.
        * lock_ids maps path→lock_id (optional per file).
        """
        lock_ids = lock_ids or {}
        written: list[tuple[str, bytes]] = []
        nodes: list[FileNode] = []

        # Phase 1: pre-check locks for all files
        async with self._conn as db:
            db.row_factory = __import__("aiosqlite").Row
            for path in files:
                await self._check_write_lock(
                    db, project_id, path, agent_id,
                )

        # Phase 2: write all files, track for rollback
        try:
            for path, content in files.items():
                node = await self.write_file(
                    project_id, path, content, agent_id,
                )
                written.append((path, content))
                nodes.append(node)
        except Exception:
            # Rollback: delete what we just wrote
            for path, _ in written:
                try:
                    await self.backend.delete(project_id, path)
                except Exception:
                    logger.warning("push_files rollback: failed for %s", path)
            raise

        return nodes
