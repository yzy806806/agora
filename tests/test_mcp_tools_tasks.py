"""Tests for task MCP tools: get_pending_tasks, accept_task."""
from __future__ import annotations

import pytest
import pytest_asyncio

from agora.coordinator.mcp.deps import init_mcp_deps
from agora.coordinator.mcp.tools.task_tools import (
    get_pending_tasks, accept_task,
)
from agora.coordinator.storage import Storage
from agora.coordinator.task_models import TaskNode


@pytest_asyncio.fixture(loop_scope="session")
async def task_storage(tmp_path):
    db_path = str(tmp_path / "test_mcp_task_tools.db")
    s = Storage(db_path)
    await s.init_db()
    # Register "unknown" agent for FK constraint
    await s.register_agent(agent_id="unknown", name="Default")
    init_mcp_deps(storage=s, token_mgr=None, ws_manager=None)
    yield s


class TestGetPendingTasks:
    @pytest.mark.asyncio
    async def test_empty_tasks(self, task_storage):
        result = await get_pending_tasks()
        assert result["tasks"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_with_pending_task(self, task_storage):
        motion = await task_storage.create_motion(
            title="T1", description="Test motion",
        )
        await task_storage.create_task_graph("g-t1", motion["id"])
        task = TaskNode(
            id="t-001", graph_id="g-t1", motion_id=motion["id"],
            title="Test task", description="Desc",
        )
        await task_storage.create_task(task)
        result = await get_pending_tasks()
        assert result["total"] >= 1


class TestAcceptTask:
    @pytest.mark.asyncio
    async def test_accept_not_found(self, task_storage):
        result = await accept_task(task_id="nonexistent")
        assert "error" in result
        assert result["code"] == 404

    @pytest.mark.asyncio
    async def test_accept_pending_task(self, task_storage):
        motion = await task_storage.create_motion(
            title="T2", description="Test motion",
        )
        await task_storage.create_task_graph("g-t2", motion["id"])
        task = TaskNode(
            id="t-002", graph_id="g-t2", motion_id=motion["id"],
            title="Pending task", description="",
        )
        await task_storage.create_task(task)
        result = await accept_task(task_id="t-002")
        assert result["task_id"] == "t-002"
        assert result["status"] == "running"
