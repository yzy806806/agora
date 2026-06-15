"""Tests for TaskNode.workspace_paths field (Phase 14.5b)."""
import pytest
import pytest_asyncio

from agora.coordinator.storage import Storage
from agora.coordinator.task_models import TaskNode, TaskStatus


@pytest_asyncio.fixture(loop_scope="session")
async def storage(tmp_path):
    db_path = str(tmp_path / "test_workspace_paths.db")
    s = Storage(db_path)
    await s.init_db()
    yield s


def test_task_node_workspace_paths_default():
    node = TaskNode(
        id="t1", graph_id="g1", motion_id="m1",
        title="Test task",
    )
    assert node.workspace_paths == []


def test_task_node_workspace_paths_set():
    node = TaskNode(
        id="t1", graph_id="g1", motion_id="m1",
        title="Test task",
        workspace_paths=["src/main.py", "src/utils.py"],
    )
    assert node.workspace_paths == ["src/main.py", "src/utils.py"]


@pytest.mark.asyncio
async def test_create_task_with_workspace_paths(storage):
    motion = await storage.create_motion("M1", "desc")
    mid = motion["id"]
    await storage.create_task_graph("g1", mid)

    task = TaskNode(
        id="t1", graph_id="g1", motion_id=mid,
        title="Task 1",
        workspace_paths=["src/main.py", "docs/README.md"],
    )
    result = await storage.create_task(task)
    assert result["workspace_paths"] == ["src/main.py", "docs/README.md"]

    fetched = await storage.get_task("t1")
    assert fetched is not None
    assert fetched["workspace_paths"] == ["src/main.py", "docs/README.md"]


@pytest.mark.asyncio
async def test_task_workspace_paths_default_empty(storage):
    motion = await storage.create_motion("M2", "desc2")
    mid = motion["id"]
    await storage.create_task_graph("g2", mid)

    task = TaskNode(
        id="t2", graph_id="g2", motion_id=mid, title="Task 2",
    )
    result = await storage.create_task(task)
    assert result["workspace_paths"] == []

    fetched = await storage.get_task("t2")
    assert fetched["workspace_paths"] == []


def test_task_model_dump_includes_workspace_paths():
    node = TaskNode(
        id="t1", graph_id="g1", motion_id="m1",
        title="Test", workspace_paths=["a.py", "b.py"],
    )
    d = node.model_dump(mode="json")
    assert "workspace_paths" in d
    assert d["workspace_paths"] == ["a.py", "b.py"]
