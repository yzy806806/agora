"""Tests for pipeline workspace_paths wiring (Phase 14.5b)."""
import pytest

from agora.coordinator.task_models import TaskNode
from agora.coordinator.pipeline_workspace import augment_graph_with_paths
from agora.coordinator.pipeline_executor import _set_workspace_paths


def test_augment_graph_sets_task_node_workspace_paths():
    t1 = TaskNode(id="t1", graph_id="g1", motion_id="m1", title="T1")
    t2 = TaskNode(id="t2", graph_id="g1", motion_id="m1", title="T2")
    graph = {
        "id": "g1", "motion_id": "m1",
        "task_ids": ["t1", "t2"],
        "tasks": [t1, t2],
    }
    artifact_paths = {"t1": ["src/a.py"], "t2": ["src/b.py", "src/c.py"]}
    result = augment_graph_with_paths(graph, artifact_paths)
    assert result["workspace_paths"]["t1"] == ["src/a.py"]
    assert result["workspace_paths"]["t2"] == ["src/b.py", "src/c.py"]
    # TaskNode objects should also be updated
    assert t1.workspace_paths == ["src/a.py"]
    assert t2.workspace_paths == ["src/b.py", "src/c.py"]


def test_augment_graph_no_artifact_paths():
    t1 = TaskNode(id="t1", graph_id="g1", motion_id="m1", title="T1")
    graph = {"id": "g1", "task_ids": ["t1"], "tasks": [t1]}
    result = augment_graph_with_paths(graph, artifact_paths=None)
    assert "workspace_paths" not in result
    assert t1.workspace_paths == []


def test_set_workspace_paths_from_graph_map():
    t1 = TaskNode(id="t1", graph_id="g1", motion_id="m1", title="T1")
    t2 = TaskNode(id="t2", graph_id="g1", motion_id="m1", title="T2")
    graph = {
        "id": "g1",
        "workspace_paths": {"t1": ["x.py"], "t2": ["y.py"]},
        "tasks": [t1, t2],
    }
    _set_workspace_paths(graph)
    assert t1.workspace_paths == ["x.py"]
    assert t2.workspace_paths == ["y.py"]


def test_set_workspace_paths_empty_map():
    t1 = TaskNode(id="t1", graph_id="g1", motion_id="m1", title="T1")
    graph = {"id": "g1", "tasks": [t1]}
    _set_workspace_paths(graph)
    assert t1.workspace_paths == []
