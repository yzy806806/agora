"""Tests for Phase 16.2: MCP Tools.

Covers all 9 MCP tools:
- register_agent, update_status
- get_pending_tasks, accept_task, submit_task_result
- send_message, list_conversations
- get_workspace_file, put_workspace_file
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from agora.coordinator.mcp.deps import init_mcp_deps
from agora.coordinator.storage import Storage


@pytest_asyncio.fixture(loop_scope="session")
async def mcp_storage(tmp_path):
    """Create a Storage instance and wire it into MCP deps."""
    db_path = str(tmp_path / "test_mcp_tools.db")
    s = Storage(db_path)
    await s.init_db()
    init_mcp_deps(storage=s, token_mgr=None, ws_manager=None)
    yield s


# --- register_agent ---

class TestRegisterAgent:
    @pytest.mark.asyncio
    async def test_register_success(self, mcp_storage):
        from agora.coordinator.mcp.tools.agent_tools import register_agent
        result = await register_agent(name="TestBot")
        assert "agent_id" in result
        assert result["agent_id"].startswith("agent-")
        assert "agent_token" in result
        assert result["agent_token"].startswith("ag-")
        assert "approval_status" in result

    @pytest.mark.asyncio
    async def test_register_with_capabilities(self, mcp_storage):
        from agora.coordinator.mcp.tools.agent_tools import register_agent
        result = await register_agent(
            name="CapBot", capabilities=["python", "review"],
        )
        assert result["agent_id"].startswith("agent-")
