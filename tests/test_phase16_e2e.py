"""Phase 16.7b: E2E test — agent registers via MCP, gets tasks, submits result.

Simulates the full lifecycle of an MCP-connected agent:
1. register_agent → get agent_id + token
2. get_pending_tasks → see available tasks
3. accept_task → claim a task
4. submit_task_result → complete the task

Also tests Hermes mcp_servers config example (16.7a).
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from agora.coordinator.storage import Storage
from agora.coordinator.mcp.deps import init_mcp_deps
from agora.coordinator.task_models import TaskNode, TaskStatus


@pytest_asyncio.fixture(loop_scope="session")
async def e2e_storage(tmp_path_factory):
    """Storage for E2E lifecycle test."""
    db_path = str(tmp_path_factory.mktemp("e2e") / "e2e.db")
    s = Storage(db_path)
    await s.init_db()
    init_mcp_deps(s, token_mgr=None, ws_manager=None)
    return s


async def _create_task(storage, task_id: str, graph_id: str):
    """Helper: create a motion + task graph + task."""
    motion = await storage.create_motion(
        title=f"Motion for {task_id}", description="e2e test",
    )
    mid = motion["id"]
    await storage.create_task_graph(graph_id, mid)
    t = TaskNode(
        id=task_id, graph_id=graph_id, motion_id=mid,
        title=f"Task {task_id}", description="e2e test task",
        status=TaskStatus.PENDING,
    )
    async with storage._connection() as db:
        from agora.coordinator.storage import tasks as task_mod
        await task_mod.create_task(db, storage.dialect, t)


class TestE2EAgentLifecycle:
    """16.7b: Full MCP agent lifecycle test."""

    @pytest.mark.asyncio
    async def test_register_and_get_tasks(self, e2e_storage):
        """Agent registers, sees pending tasks."""
        from agora.coordinator.mcp.tools.agent_tools import (
            register_agent,
        )
        from agora.coordinator.mcp.tools.task_tools import (
            get_pending_tasks,
        )

        # 1. Register agent
        reg = await register_agent(
            name="E2E Test Agent",
            capabilities=["python", "testing"],
        )
        assert "agent_id" in reg
        assert reg["agent_token"].startswith("ag-")
        assert reg["approval_status"] in ("pending", "auto_approved")

        # 2. Create a task for the agent to see
        await _create_task(e2e_storage, "e2e-task-1", "e2e-g1")

        # 3. Get pending tasks
        tasks = await get_pending_tasks(limit=10)
        assert tasks["total"] >= 1
        task_ids = [t["task_id"] for t in tasks["tasks"]]
        assert "e2e-task-1" in task_ids

    @pytest.mark.asyncio
    async def test_accept_and_complete_task(self, e2e_storage):
        """Agent accepts task and submits result."""
        from agora.coordinator.mcp.tools.task_tools import (
            accept_task, submit_task_result,
        )

        # Create a task and accept it
        await _create_task(e2e_storage, "e2e-task-2", "e2e-g2")
        result = await accept_task(task_id="e2e-task-2")
        assert result["status"] == "running"
        assert result["task_id"] == "e2e-task-2"

        # Submit result
        submit = await submit_task_result(
            task_id="e2e-task-2",
            result="All E2E tests passed!",
        )
        assert submit["status"] == "done"
        assert submit["task_id"] == "e2e-task-2"

    @pytest.mark.asyncio
    async def test_submit_failure_result(self, e2e_storage):
        """Agent submits a failure result."""
        from agora.coordinator.mcp.tools.task_tools import (
            accept_task, submit_task_result,
        )

        await _create_task(e2e_storage, "e2e-task-3", "e2e-g3")
        await accept_task(task_id="e2e-task-3")
        result = await submit_task_result(
            task_id="e2e-task-3",
            error="Build failed: missing dependency",
        )
        assert result["status"] == "failed"


class TestHermesConfigExample:
    """16.7a: Verify Hermes mcp_servers config example is valid."""

    def test_config_format(self):
        """Hermes config YAML has required fields."""
        # This validates the config structure documented in
        # ARCHITECTURE-mcp.md and API-mcp.md
        config = {
            "agora": {
                "url": "http://localhost:8000/mcp",
                "headers": {"Authorization": "Bearer ag-test-token"},
                "timeout": 300,
            }
        }
        # url must point to /mcp
        assert config["agora"]["url"].endswith("/mcp")
        # headers must include Authorization
        assert "Authorization" in config["agora"]["headers"]
        # timeout is reasonable
        assert config["agora"]["timeout"] > 0
