"""Tests for StorageBackend ABC + LocalFileBackend."""

import hashlib
import pytest

from agora.coordinator.workspace.backend import StorageBackend, get_storage_backend
from agora.coordinator.workspace.local_backend import LocalFileBackend


# --- StorageBackend ABC ---


def test_abc_cannot_instantiate():
    """StorageBackend is abstract and cannot be instantiated."""
    with pytest.raises(TypeError):
        StorageBackend()  # type: ignore[abstract]


# --- LocalFileBackend ---


@pytest.fixture
def backend(tmp_path):
    return LocalFileBackend(root=str(tmp_path))


@pytest.mark.asyncio
async def test_put_and_get(backend):
    sha = await backend.put("proj1", "a.txt", b"hello", "text/plain")
    assert sha == hashlib.sha256(b"hello").hexdigest()
    data = await backend.get("proj1", "a.txt")
    assert data == b"hello"


@pytest.mark.asyncio
async def test_get_missing(backend):
    assert await backend.get("proj1", "missing.txt") is None


@pytest.mark.asyncio
async def test_exists(backend):
    await backend.put("proj1", "a.txt", b"data", "text/plain")
    assert await backend.exists("proj1", "a.txt") is True
    assert await backend.exists("proj1", "nope.txt") is False


@pytest.mark.asyncio
async def test_delete(backend):
    await backend.put("proj1", "a.txt", b"data", "text/plain")
    assert await backend.delete("proj1", "a.txt") is True
    assert await backend.get("proj1", "a.txt") is None
    assert await backend.delete("proj1", "a.txt") is False


@pytest.mark.asyncio
async def test_put_creates_subdirs(backend):
    await backend.put("proj1", "sub/dir/a.txt", b"deep", "text/plain")
    assert await backend.get("proj1", "sub/dir/a.txt") == b"deep"
