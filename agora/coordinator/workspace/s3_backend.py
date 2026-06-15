"""S3Backend — S3-compatible object storage for workspace content."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, AsyncIterator

import aiobotocore.session
from botocore.config import Config as BotoConfig

from .backend import StorageBackend

logger = logging.getLogger(__name__)


class S3Backend(StorageBackend):
    """Stores files in S3-compatible object storage (MinIO / AWS S3)."""

    def __init__(
        self,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        prefix: str = "",
        region: str = "us-east-1",
    ) -> None:
        self._endpoint_url = endpoint_url
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._region = region
        self._s3_config = BotoConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        )
        self._creds: dict[str, Any] = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": region,
            "endpoint_url": endpoint_url,
            "config": self._s3_config,
        }

    def _key(self, project_id: str, path: str) -> str:
        """Build S3 object key from project_id and path."""
        safe = path.lstrip("/").replace("..", "")
        parts = [p for p in (self._prefix, project_id, safe) if p]
        return "/".join(parts)

    def _get_client(self) -> Any:
        """Create an aiobotocore S3 client context manager.

        Returns an async context manager yielding an S3 client.
        Override in tests to inject mocks.
        """
        session = aiobotocore.session.get_session()
        return session.create_client("s3", **self._creds)

    async def put(
        self, project_id: str, path: str,
        content: bytes, content_type: str,
    ) -> str:
        key = self._key(project_id, path)
        sha = hashlib.sha256(content).hexdigest()
        async with self._get_client() as s3:
            await s3.put_object(
                Bucket=self._bucket, Key=key, Body=content,
                ContentType=content_type,
                Metadata={"sha256": sha},
            )
        return sha

    async def get(self, project_id: str, path: str) -> bytes | None:
        key = self._key(project_id, path)
        async with self._get_client() as s3:
            try:
                resp = await s3.get_object(
                    Bucket=self._bucket, Key=key,
                )
                async with resp["Body"] as stream:
                    return await stream.read()
            except Exception:
                logger.debug("S3 get failed key=%s", key, exc_info=True)
                return None

    async def delete(self, project_id: str, path: str) -> bool:
        key = self._key(project_id, path)
        async with self._get_client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
            except Exception:
                return False
            await s3.delete_object(Bucket=self._bucket, Key=key)
            return True

    async def exists(self, project_id: str, path: str) -> bool:
        key = self._key(project_id, path)
        async with self._get_client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
                return True
            except Exception:
                return False

    async def get_range(
        self, project_id: str, path: str,
        offset: int, length: int,
    ) -> bytes:
        key = self._key(project_id, path)
        end = offset + length - 1
        async with self._get_client() as s3:
            resp = await s3.get_object(
                Bucket=self._bucket, Key=key,
                Range=f"bytes={offset}-{end}",
            )
            async with resp["Body"] as stream:
                return await stream.read()

    async def get_presigned_url(
        self, project_id: str, path: str,
        expires: int = 3600,
    ) -> str:
        """Generate a presigned URL for direct S3 access."""
        key = self._key(project_id, path)
        async with self._get_client() as s3:
            return await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires,
            )
