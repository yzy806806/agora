"""LocalFileBackend — local filesystem storage for workspace content."""

from __future__ import annotations

import hashlib
from pathlib import Path

import aiofiles

from .backend import StorageBackend


class LocalFileBackend(StorageBackend):
    """Stores files on the local filesystem under a root directory."""

    def __init__(self, root: str = "./data/workspaces") -> None:
        self.root = Path(root).resolve()

    def _resolve(self, project_id: str, path: str) -> Path:
        """Normalize path and prevent directory traversal."""
        safe = path.lstrip("/").replace("..", "")
        resolved = (self.root / project_id / safe).resolve()
        if not str(resolved).startswith(str(self.root)):
            msg = f"Path traversal blocked: {path}"
            raise ValueError(msg)
        return resolved

    async def put(
        self, project_id: str, path: str,
        content: bytes, content_type: str,
    ) -> str:
        full = self._resolve(project_id, path)
        full.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(full, "wb") as f:
            await f.write(content)
        return hashlib.sha256(content).hexdigest()

    async def get(self, project_id: str, path: str) -> bytes | None:
        full = self._resolve(project_id, path)
        if not full.is_file():
            return None
        async with aiofiles.open(full, "rb") as f:
            return await f.read()

    async def delete(self, project_id: str, path: str) -> bool:
        full = self._resolve(project_id, path)
        if not full.is_file():
            return False
        full.unlink()
        return True

    async def exists(self, project_id: str, path: str) -> bool:
        return self._resolve(project_id, path).is_file()

    async def get_range(
        self, project_id: str, path: str,
        offset: int, length: int,
    ) -> bytes:
        full = self._resolve(project_id, path)
        async with aiofiles.open(full, "rb") as f:
            await f.seek(offset)
            return await f.read(length)
