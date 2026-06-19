"""Workspace package — pluggable storage backends + manager + REST API."""

from .backend import StorageBackend, get_storage_backend
from .local_backend import LocalFileBackend
from .lock_manager import LockManager
from .manager import WorkspaceManager
from .manager_bulk import WorkspaceManagerBulkOps
from .manager_dirs import WorkspaceManagerDirOps
from .models import FileLock, FileNode, FileType, LockType
from .s3_backend import S3Backend
from .ws_messages import (
    emit_file_changed,
    emit_file_deleted,
    emit_lock_acquired,
    emit_lock_expired,
    emit_lock_released,
)
from .workspace_router import router as workspace_router
from .workspace_router import init_workspace_router_deps
from .workspace_router_helpers import _extract_agent_id, parse_range_header
from .workspace_router_read import router_read as workspace_router_read
from .workspace_router_dirs import router_dirs as workspace_router_dirs
from .workspace_router_locks import router_locks as workspace_router_locks

__all__ = [
    "StorageBackend", "LocalFileBackend", "S3Backend",
    "get_storage_backend",
    "WorkspaceManager", "WorkspaceManagerBulkOps",
    "WorkspaceManagerDirOps", "LockManager",
    "FileNode", "FileType", "FileLock", "LockType",
    "workspace_router", "workspace_router_read",
    "init_workspace_router_deps",
    "_extract_agent_id", "parse_range_header",
    "workspace_router_dirs", "workspace_router_locks",
    "emit_file_changed", "emit_file_deleted",
    "emit_lock_acquired", "emit_lock_released", "emit_lock_expired",
]
