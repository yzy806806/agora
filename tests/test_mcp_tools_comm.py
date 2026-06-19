"""Tests for comm MCP tools: send_message, list_conversations."""
from __future__ import annotations

import pytest
import pytest_asyncio

from agora.coordinator.mcp.deps import init_mcp_deps
from agora.coordinator.mcp.tools.comm_tools import (
    send_message, list_conversations,
)
from agora.coordinator.storage import Storage


@pytest_asyncio.fixture(loop_scope="session")
async def comm_storage(tmp_path):
    db_path = str(tmp_path / "test_mcp_comm_tools.db")
    s = Storage(db_path)
    await s.init_db()
    init_mcp_deps(storage=s, token_mgr=None, ws_manager=None)
    yield s


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_conversation_not_found(self, comm_storage):
        result = await send_message(
            conversation_id="nonexistent", message="hello",
        )
        assert "error" in result
        assert result["code"] == 404

    @pytest.mark.asyncio
    async def test_send_to_discussion(self, comm_storage):
        # Need an agent for FK constraint on messages
        await comm_storage.register_agent(
            agent_id="unknown", name="Default",
        )
        motion = await comm_storage.create_motion(
            title="Test", description="Test motion",
        )
        conv_id = motion["id"]
        await comm_storage.update_motion_status(conv_id, "discussion")
        result = await send_message(
            conversation_id=conv_id,
            message="I support this",
            stance="support",
        )
        assert "message_id" in result
        assert "timestamp" in result


class TestListConversations:
    @pytest.mark.asyncio
    async def test_empty_list(self, comm_storage):
        result = await list_conversations()
        assert "conversations" in result
        assert "total" in result

    @pytest.mark.asyncio
    async def test_with_discussion_motion(self, comm_storage):
        motion = await comm_storage.create_motion(
            title="New Motion", description="Test",
        )
        # Set to discussing status so it matches "active" filter
        await comm_storage.update_motion_status(
            motion["id"], "discussion")
        result = await list_conversations(status_filter="all")
        assert result["total"] >= 1
