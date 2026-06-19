"""Tests for submit_task_result MCP tool."""
from __future__ import annotations

import pytest
import pytest_asyncio

from agora.coordinator.mcp.deps import init_mcp_deps
from agora.coordinator.mcp.tools.task_tools import submit_task_result
from agora.coordinator.storage import Storage
from agora.coordinator.task_models import TaskNode


@pytest_asyncio.fixture(loop_scope="session")
async def result_storage(tmp_path):
    db_path = str(tmp_path / "test_mcp_result_tools.db")
    s = Storage(db_path)
    await s.init_db()
    # Register "unknown" agent for FK constraint
    await s.register_agent(agent_id="unknown", name="Default")
    init_mcp_deps(storage=s, token_mgr=None, ws_manager=None)
    yield s


async def _make_running_task(storage, tid, gid, mid):
    """Helper: create a task and set it to running."""
    await storage.create_task_graph(gid, mid)
    task = TaskNode(
        id=tid, graph_id=gid, motion_id=mid,
        title="Running task", description="",
    )
    await storage.create_task(task)
    # Don't assign to a specific agent so the ownership
    # check in submit_task_result passes in test context
    # (where _get_current_agent_id() returns None)
    await storage.update_task_status(tid, "running")


class TestSubmitTaskResult:
    @pytest.mark.asyncio
    async def test_task_not_found(self, result_storage):
        result = await submit_task_result(task_id="nonexistent")
        assert "error" in result
        assert result["code"] == 404

    @pytest.mark.asyncio
    async def test_submit_success(self, result_storage):
        motion = await result_storage.create_motion(
            title="R1", description="Test",
        )
        await _make_running_task(
            result_storage, "t-r1", "g-r1", motion["id"])
        result = await submit_task_result(task_id="t-r1", result="Done")
        assert result["task_id"] == "t-r1"
        assert result["status"] == "done"

    @pytest.mark.asyncio
    async def test_submit_failure(self, result_storage):
        motion = await result_storage.create_motion(
            title="R2", description="Test",
        )
        await _make_running_task(
            result_storage, "t-r2", "g-r2", motion["id"])
        result = await submit_task_result(
            task_id="t-r2", error="Something went wrong",
        )
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_wrong_status(self, result_storage):
        motion = await result_storage.create_motion(
            title="R3", description="Test",
        )
        await result_storage.create_task_graph("g-r3", motion["id"])
        task = TaskNode(
            id="t-r3", graph_id="g-r3", motion_id=motion["id"],
            title="Done task", description="",
        )
        await result_storage.create_task(task)
        await result_storage.update_task_status("t-r3", "running")
        await result_storage.update_task_status("t-r3", "done")
        result = await submit_task_result(task_id="t-r3")
        assert "error" in result
        assert result["code"] == 409
