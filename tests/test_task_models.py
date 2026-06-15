"""Tests for Task Models and Task CRUD operations."""

import pytest
import pytest_asyncio

from agora.coordinator.storage import Storage
from agora.coordinator.task_models import (
    TaskGraph, TaskNode, TaskStatus, TaskPriority,
)


@pytest_asyncio.fixture(loop_scope="session")
async def storage(tmp_path):
    """Create a Storage instance with a temporary database."""
    db_path = str(tmp_path / "test_tasks.db")
    s = Storage(db_path)
    await s.init_db()
    yield s


# --- Task Models ---

def test_task_status_values():
    assert TaskStatus.PENDING == "pending"
    assert TaskStatus.ASSIGNED == "assigned"
    assert TaskStatus.RUNNING == "running"
    assert TaskStatus.DONE == "done"
    assert TaskStatus.ACCEPTED == "accepted"
    assert TaskStatus.REJECTED == "rejected"
    assert TaskStatus.FAILED == "failed"


def test_task_priority_values():
    assert TaskPriority.LOW == "low"
    assert TaskPriority.NORMAL == "normal"
    assert TaskPriority.HIGH == "high"
    assert TaskPriority.CRITICAL == "critical"


def test_task_node_defaults():
    node = TaskNode(
        id="t1", graph_id="g1", motion_id="m1",
        title="Test task", description="desc",
    )
    assert node.status == TaskStatus.PENDING
    assert node.assigned_to is None
    assert node.required_capabilities == []
    assert node.depends_on == []
    assert node.artifact_paths == []
    assert node.workspace_paths == []
    assert node.error_message is None
    assert node.started_at is None
    assert node.completed_at is None


def test_task_graph_creation():
    graph = TaskGraph(id="g1", motion_id="m1")
    assert graph.tasks == []
    assert graph.created_at is not None
