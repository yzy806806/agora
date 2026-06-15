"""Tests for get_range, path traversal, and factory."""


import pytest

from agora.coordinator.workspace.backend import get_storage_backend
from agora.coordinator.workspace.local_backend import LocalFileBackend


@pytest.fixture
def backend(tmp_path):
    return LocalFileBackend(root=str(tmp_path))


@pytest.mark.asyncio
async def test_get_range(backend):
    await backend.put("proj1", "data.bin", b"0123456789", "application/octet-stream")
    chunk = await backend.get_range("proj1", "data.bin", 3, 4)
    assert chunk == b"3456"


@pytest.mark.asyncio
async def test_path_traversal_blocked(backend):
    with pytest.raises(ValueError, match="Path traversal"):
        await backend.get("proj1", "../../../etc/passwd")


@pytest.mark.asyncio
async def test_leading_slash_stripped(backend):
    await backend.put("proj1", "/leading/slash.txt", b"ok", "text/plain")
    data = await backend.get("proj1", "/leading/slash.txt")
    assert data == b"ok"


# --- Factory ---


def test_factory_default():
    be = get_storage_backend({})
    assert isinstance(be, LocalFileBackend)


def test_factory_local_with_root(tmp_path):
    be = get_storage_backend({"backend": "local", "local": {"root": str(tmp_path)}})
    assert isinstance(be, LocalFileBackend)
    assert be.root == tmp_path.resolve()


def test_factory_unknown():
    with pytest.raises(ValueError, match="Unknown storage backend"):
        get_storage_backend({"backend": "gcs"})
