"""Tests for workspace models: FileNode, FileLock, enums."""

from datetime import datetime, timedelta

import pytest
from agora.coordinator.workspace.models import (
    FileLock, FileNode, FileType, LockType,
)


# --- FileType enum ---

class TestFileType:
    def test_values(self):
        assert FileType.FILE.value == "file"
        assert FileType.DIRECTORY.value == "directory"

    def test_is_str_enum(self):
        assert isinstance(FileType.FILE, str)
        assert FileType.FILE == "file"


# --- LockType enum ---

class TestLockType:
    def test_values(self):
        assert LockType.READ.value == "read"
        assert LockType.WRITE.value == "write"

    def test_is_str_enum(self):
        assert isinstance(LockType.READ, str)


# --- FileNode ---

class TestFileNode:
    def _make_node(self, **overrides):
        defaults = dict(
            project_id="proj-1", path="src/main.py",
            name="main.py", file_type=FileType.FILE,
            parent_path="src", created_by="agent-1",
        )
        defaults.update(overrides)
        return FileNode(**defaults)

    def test_create_file_node(self):
        node = self._make_node()
        assert node.id  # auto-generated UUID
        assert node.project_id == "proj-1"
        assert node.path == "src/main.py"
        assert node.file_type == FileType.FILE
        assert node.size == 0
        assert node.content_type == "application/octet-stream"
        assert node.checksum_sha256 is None
        assert node.version == 1
        assert isinstance(node.created_at, datetime)

    def test_directory_node(self):
        node = self._make_node(
            path="src", name="src",
            file_type=FileType.DIRECTORY, parent_path=None,
        )
        assert node.file_type == FileType.DIRECTORY
        assert node.parent_path is None

    def test_custom_defaults(self):
        node = self._make_node(
            size=1024, content_type="text/plain",
            checksum_sha256="abc123", version=3,
        )
        assert node.size == 1024
        assert node.content_type == "text/plain"
        assert node.checksum_sha256 == "abc123"
        assert node.version == 3

    def test_serialization_roundtrip(self):
        node = self._make_node()
        data = node.model_dump()
        restored = FileNode.model_validate(data)
        assert restored == node


# --- FileLock ---

class TestFileLock:
    def _make_lock(self, **overrides):
        defaults = dict(
            file_id="f-1", project_id="proj-1",
            path="src/main.py", lock_type=LockType.WRITE,
            held_by="agent-1",
            expires_at=datetime.utcnow() + timedelta(minutes=5),
        )
        defaults.update(overrides)
        return FileLock(**defaults)

    def test_create_write_lock(self):
        lock = self._make_lock()
        assert lock.id  # auto UUID
        assert lock.lock_type == LockType.WRITE
        assert lock.held_by == "agent-1"
        assert lock.expires_at > lock.acquired_at

    def test_read_lock(self):
        lock = self._make_lock(lock_type=LockType.READ)
        assert lock.lock_type == LockType.READ

    def test_serialization_roundtrip(self):
        lock = self._make_lock()
        data = lock.model_dump()
        restored = FileLock.model_validate(data)
        assert restored == lock
