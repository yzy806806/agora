"""StorageBackend ABC + factory for workspace file content."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
    """Pluggable storage for workspace file content."""

    @abstractmethod
    async def put(
        self, project_id: str, path: str,
        content: bytes, content_type: str,
    ) -> str:
        """Store file content. Returns checksum_sha256."""

    @abstractmethod
    async def get(self, project_id: str, path: str) -> bytes | None:
        """Retrieve file content. Returns None if not found."""

    @abstractmethod
    async def delete(self, project_id: str, path: str) -> bool:
        """Delete file content. Returns True if existed."""

    @abstractmethod
    async def exists(self, project_id: str, path: str) -> bool:
        """Check if file content exists."""

    @abstractmethod
    async def get_range(
        self, project_id: str, path: str,
        offset: int, length: int,
    ) -> bytes:
        """Read a byte range (for large file streaming)."""


def get_storage_backend(config: dict[str, Any]) -> StorageBackend:
    """Factory: create backend from config dict (workspace section)."""
    backend_type = config.get("backend", "local")
    if backend_type == "local":
        from .local_backend import LocalFileBackend

        root = config.get("local", {}).get("root", "./data/workspaces")
        return LocalFileBackend(root=root)
    if backend_type == "s3":
        from .s3_backend import S3Backend

        s3_cfg = config.get("s3", {})
        return S3Backend(
            endpoint_url=s3_cfg.get("endpoint", "http://minio:9000"),
            bucket=s3_cfg.get("bucket", "agora-workspaces"),
            access_key=s3_cfg.get("access_key", ""),
            secret_key=s3_cfg.get("secret_key", ""),
            prefix=s3_cfg.get("prefix", ""),
            region=s3_cfg.get("region", "us-east-1"),
        )
    msg = f"Unknown storage backend: {backend_type}"
    raise ValueError(msg)
