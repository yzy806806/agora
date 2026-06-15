"""Tests for S3Backend using mock client injection."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from agora.coordinator.workspace.s3_backend import S3Backend
from agora.coordinator.workspace.backend import get_storage_backend


def _make_backend(**kw) -> S3Backend:
    defaults = dict(
        endpoint_url="http://minio:9000", bucket="agora-ws",
        access_key="ak", secret_key="sk",
    )
    defaults.update(kw)
    return S3Backend(**defaults)


def _inject_mock(backend: S3Backend):
    """Replace _get_client with a mock-returning context manager."""
    client = AsyncMock()
    # Set up client.exceptions.NoSuchKey
    client.exceptions = MagicMock(NoSuchKey=type("NoSuchKey", (Exception,), {}))

    @asynccontextmanager
    async def _mock_get_client():
        yield client

    backend._get_client = _mock_get_client  # noqa: SLF001
    return client


@pytest.mark.asyncio
async def test_put():
    b = _make_backend()
    c = _inject_mock(b)
    sha = await b.put("p1", "a.txt", b"hello", "text/plain")
    assert sha == hashlib.sha256(b"hello").hexdigest()
    c.put_object.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_found():
    b = _make_backend()
    c = _inject_mock(b)
    body = AsyncMock()
    body.read = AsyncMock(return_value=b"data")
    body.__aenter__ = AsyncMock(return_value=body)
    body.__aexit__ = AsyncMock(return_value=False)
    c.get_object = AsyncMock(return_value={"Body": body})
    data = await b.get("p1", "a.txt")
    assert data == b"data"


@pytest.mark.asyncio
async def test_get_missing():
    b = _make_backend()
    c = _inject_mock(b)
    c.get_object = AsyncMock(side_effect=Exception("NoSuchKey"))
    assert await b.get("p1", "missing") is None


@pytest.mark.asyncio
async def test_exists():
    b = _make_backend()
    c = _inject_mock(b)
    c.head_object = AsyncMock(return_value={})
    assert await b.exists("p1", "a.txt") is True
    c.head_object = AsyncMock(side_effect=Exception("404"))
    assert await b.exists("p1", "a.txt") is False


@pytest.mark.asyncio
async def test_delete():
    b = _make_backend()
    c = _inject_mock(b)
    c.head_object = AsyncMock(return_value={})
    c.delete_object = AsyncMock()
    assert await b.delete("p1", "a.txt") is True
    c.head_object = AsyncMock(side_effect=Exception("404"))
    assert await b.delete("p1", "a.txt") is False


@pytest.mark.asyncio
async def test_get_range():
    b = _make_backend()
    c = _inject_mock(b)
    body = AsyncMock()
    body.read = AsyncMock(return_value=b"2345")
    body.__aenter__ = AsyncMock(return_value=body)
    body.__aexit__ = AsyncMock(return_value=False)
    c.get_object = AsyncMock(return_value={"Body": body})
    chunk = await b.get_range("p1", "big.bin", 2, 4)
    assert chunk == b"2345"
    kw = c.get_object.call_args.kwargs
    assert kw["Range"] == "bytes=2-5"


@pytest.mark.asyncio
async def test_presigned_url():
    b = _make_backend()
    c = _inject_mock(b)
    c.generate_presigned_url = AsyncMock(
        return_value="http://minio:9000/agora-ws/p1/f.txt?X-Amz-Signature=abc",
    )
    url = await b.get_presigned_url("p1", "f.txt", expires=7200)
    assert "agora-ws" in url
    c.generate_presigned_url.assert_awaited_once()


def test_key_with_prefix():
    b = _make_backend(prefix="my-prefix")
    assert b._key("p1", "a.txt") == "my-prefix/p1/a.txt"
    assert b._key("p1", "/x/y.txt") == "my-prefix/p1/x/y.txt"


def test_key_without_prefix():
    b = _make_backend()
    assert b._key("p1", "a.txt") == "p1/a.txt"
    assert b._key("p1", "/a.txt") == "p1/a.txt"


def test_factory_s3():
    cfg = {
        "backend": "s3",
        "s3": {
            "endpoint": "http://minio:9000",
            "bucket": "agora-ws",
            "access_key": "ak",
            "secret_key": "sk",
            "prefix": "pre",
        },
    }
    backend = get_storage_backend(cfg)
    assert isinstance(backend, S3Backend)
    assert backend._prefix == "pre"


def test_factory_unknown_raises():
    with pytest.raises(ValueError, match="Unknown storage backend"):
        get_storage_backend({"backend": "gcs"})
