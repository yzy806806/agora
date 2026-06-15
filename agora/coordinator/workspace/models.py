"""Workspace data models: FileNode and FileLock."""

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class FileType(str, Enum):
    """Node type in the virtual filesystem."""
    FILE = "file"
    DIRECTORY = "directory"


class LockType(str, Enum):
    """Lock type for concurrency control."""
    READ = "read"       # shared: multiple readers
    WRITE = "write"     # exclusive: one writer, no readers


class FileNode(BaseModel):
    """A node in the workspace virtual filesystem."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    path: str                           # e.g. "src/main.py"
    name: str                           # e.g. "main.py"
    file_type: FileType
    parent_path: str | None = None      # e.g. "src"; None for root
    size: int = 0                       # bytes (0 for directories)
    content_type: str = "application/octet-stream"
    checksum_sha256: str | None = None
    created_by: str                     # agent_id
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = 1                    # monotonically increasing


class FileLock(BaseModel):
    """Tracks an active file lock for concurrency control."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    file_id: str                        # FK → file_nodes.id
    project_id: str
    path: str                           # denormalized for fast lookup
    lock_type: LockType
    held_by: str                        # agent_id
    acquired_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime                # auto-release on expiry
