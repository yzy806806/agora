"""Tests for pipeline_workspace.py helpers (Phase 14.5a)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from agora.coordinator.pipeline_workspace import (
    ensure_project_root, augment_graph_with_paths,
)


@pytest.mark.asyncio
async def test_ensure_project_root_creates_dir():
    """ensure_project_root calls mkdir on workspace manager."""
    ws = MagicMock()
    ws.mkdir = AsyncMock()
    await ensure_project_root(ws, "proj-1")
    ws.mkdir.assert_awaited_once_with("proj-1", "", "coordinator")


@pytest.mark.asyncio
async def test_ensure_project_root_handles_existing():
    """ensure_project_root logs debug when dir already exists."""
    ws = MagicMock()
    ws.mkdir = AsyncMock(side_effect=Exception("exists"))
    # Should not raise — just logs
    await ensure_project_root(ws, "proj-1")


def test_augment_graph_no_artifact_paths():
    """augment_graph_with_paths returns graph unchanged if no paths."""
    graph = {"id": "g1", "task_ids": ["t1", "t2"]}
    result = augment_graph_with_paths(graph, None)
    assert "workspace_paths" not in result


def test_augment_graph_with_artifact_paths():
    """augment_graph_with_paths maps task_id → file paths."""
    graph = {"id": "g1", "task_ids": ["t1", "t2"]}
    artifacts = {"t1": ["src/main.py", "README.md"], "t2": ["tests/test.py"]}
    result = augment_graph_with_paths(graph, artifacts)
    assert result["workspace_paths"]["t1"] == ["src/main.py", "README.md"]
    assert result["workspace_paths"]["t2"] == ["tests/test.py"]


def test_augment_graph_missing_task_in_artifacts():
    """augment_graph_with_paths defaults to [] for missing tasks."""
    graph = {"id": "g1", "task_ids": ["t1", "t2"]}
    artifacts = {"t1": ["src/main.py"]}
    result = augment_graph_with_paths(graph, artifacts)
    assert result["workspace_paths"]["t1"] == ["src/main.py"]
    assert result["workspace_paths"]["t2"] == []
