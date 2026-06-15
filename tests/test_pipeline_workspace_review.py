"""Tests for pipeline_workspace_review.py helpers (Phase 14.5a)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from agora.coordinator.pipeline_workspace_review import (
    collect_workspace_changed_files, pull_workspace_files,
)
from agora.coordinator.workspace.models import FileNode, FileType


def _file_node(path: str) -> FileNode:
    """Create a minimal FileNode for testing."""
    return FileNode(
        project_id="proj-1", path=path,
        name=path.rsplit("/", 1)[-1], file_type=FileType.FILE,
        created_by="agent-1",
    )


def _dir_node(path: str) -> FileNode:
    """Create a minimal directory FileNode for testing."""
    return FileNode(
        project_id="proj-1", path=path,
        name=path.rsplit("/", 1)[-1], file_type=FileType.DIRECTORY,
        created_by="agent-1",
    )


@pytest.mark.asyncio
async def test_collect_workspace_changed_files():
    """collect_workspace_changed_files returns file paths only."""
    ws = MagicMock()
    ws.list_dir = AsyncMock(return_value=[
        _dir_node("src"), _file_node("src/main.py"),
        _file_node("README.md"),
    ])
    graph = {"id": "g1", "changed_files": []}
    paths = await collect_workspace_changed_files(ws, "proj-1", graph)
    assert paths == ["src/main.py", "README.md"]


@pytest.mark.asyncio
async def test_collect_workspace_falls_back_on_error():
    """collect_workspace_changed_files falls back to graph on error."""
    ws = MagicMock()
    ws.list_dir = AsyncMock(side_effect=Exception("db error"))
    graph = {"id": "g1", "changed_files": ["fallback.py"]}
    paths = await collect_workspace_changed_files(ws, "proj-1", graph)
    assert paths == ["fallback.py"]


@pytest.mark.asyncio
async def test_pull_workspace_files():
    """pull_workspace_files returns {path: content} dict."""
    ws = MagicMock()
    ws.pull_files = AsyncMock(return_value={"a.py": b"code", "b.py": b"more"})
    result = await pull_workspace_files(ws, "proj-1", ["a.py", "b.py"])
    assert result == {"a.py": b"code", "b.py": b"more"}


@pytest.mark.asyncio
async def test_pull_workspace_files_on_error():
    """pull_workspace_files returns empty dict on failure."""
    ws = MagicMock()
    ws.pull_files = AsyncMock(side_effect=Exception("oops"))
    result = await pull_workspace_files(ws, "proj-1", ["a.py"])
    assert result == {}
