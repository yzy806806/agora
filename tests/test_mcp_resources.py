"""Tests for Phase 16.3: MCP Resources.

Covers all 4 MCP Resource URI templates:
- agora://tasks/{task_id}
- agora://agents/{agent_id}/status
- agora://conversations/{conv_id}/messages
- agora://projects/{project_id}/overview
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio

from agora.coordinator.mcp.deps import init_mcp_deps, get_storage
from agora.coordinator.mcp.resources import (
    task_resources,
    agent_resources,
    conversation_resources,
    project_resources,
)
from agora.coordinator.storage import Storage


@pytest_asyncio.fixture(loop_scope="session")
async def mcp_storage(tmp_path):
    """Create a Storage instance and wire it into MCP deps."""
    db_path = str(tmp_path / "test_mcp_resources.db")
    s = Storage(db_path)
    await s.init_db()
    init_mcp_deps(storage=s, token_mgr=None, ws_manager=None)
    yield s


class TestTaskResource:
    """agora://tasks/{task_id} resource tests."""

    @pytest.mark.asyncio
    async def test_task_found(self, mcp_storage: Storage):
        from agora.coordinator.task_models import TaskNode

        # FK chain: motions → task_graphs → tasks
        motion = await mcp_storage.create_motion(
            title="Test Motion", description="For task test")
        await mcp_storage.create_task_graph("g-001", motion["id"])
        task = TaskNode(
            id="t-001",
            graph_id="g-001",
            motion_id=motion["id"],
            title="Test task",
            description="A test task",
        )
        await mcp_storage.create_task(task)
        result = await task_resources.get_task_resource("t-001")
        data = json.loads(result)
        assert data["id"] == "t-001"
        assert data["title"] == "Test task"
        assert "task_result" not in data

    @pytest.mark.asyncio
    async def test_task_not_found(self, mcp_storage: Storage):
        result = await task_resources.get_task_resource("nonexistent")
        data = json.loads(result)
        assert "error" in data
        assert data["task_id"] == "nonexistent"


class TestAgentResource:
    """agora://agents/{agent_id}/status resource tests."""

    @pytest.mark.asyncio
    async def test_agent_found(self, mcp_storage: Storage):
        await mcp_storage.register_agent(
            agent_id="a-001", name="TestAgent",
            capabilities=["python"],
            agent_token="ag-testtoken",
        )
        result = await agent_resources.get_agent_status_resource("a-001")
        data = json.loads(result)
        assert data["agent_id"] == "a-001"
        assert data["name"] == "TestAgent"
        # Sensitive fields must be stripped
        assert "agent_token" not in data
        assert "registration_token" not in data

    @pytest.mark.asyncio
    async def test_agent_not_found(self, mcp_storage: Storage):
        result = await agent_resources.get_agent_status_resource(
            "nonexistent")
        data = json.loads(result)
        assert "error" in data
        assert data["agent_id"] == "nonexistent"


class TestConversationResource:
    """agora://conversations/{conv_id}/messages resource tests."""

    @pytest.mark.asyncio
    async def test_conversation_with_messages(
        self, mcp_storage: Storage,
    ):
        # FK: messages.agent_id references agents
        await mcp_storage.register_agent(
            agent_id="a-001", name="TestAgent")
        motion = await mcp_storage.create_motion(
            title="Test Motion", description="A test motion")
        conv_id = motion["id"]
        await mcp_storage.add_message(
            motion_id=conv_id, agent_id="a-001",
            round_num=1, stance="support", content="I agree",
        )
        result = await conversation_resources.get_conversation_messages(
            conv_id)
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["agent_id"] == "a-001"
        assert data[0]["content"] == "I agree"
        assert data[0]["stance"] == "support"

    @pytest.mark.asyncio
    async def test_conversation_not_found(self, mcp_storage: Storage):
        result = await conversation_resources.get_conversation_messages(
            "nonexistent")
        data = json.loads(result)
        assert "error" in data
        assert data["conv_id"] == "nonexistent"

    @pytest.mark.asyncio
    async def test_conversation_empty(self, mcp_storage: Storage):
        motion = await mcp_storage.create_motion(
            title="Empty Motion", description="No messages")
        result = await conversation_resources.get_conversation_messages(
            motion["id"])
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 0


class TestProjectResource:
    """agora://projects/{project_id}/overview resource tests."""

    @pytest.mark.asyncio
    async def test_project_found(self, mcp_storage: Storage):
        await mcp_storage.create_pipeline_run(
            project_id="proj-001", idea="Build feature X")
        result = await project_resources.get_project_overview("proj-001")
        data = json.loads(result)
        assert data["project_id"] == "proj-001"
        assert data["pipeline_count"] >= 1
        assert len(data["recent_pipelines"]) >= 1

    @pytest.mark.asyncio
    async def test_project_not_found(self, mcp_storage: Storage):
        result = await project_resources.get_project_overview(
            "nonexistent-proj")
        data = json.loads(result)
        assert "error" in data
        assert data["project_id"] == "nonexistent-proj"
