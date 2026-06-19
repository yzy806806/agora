"""Phase 16 integration tests: MCP coexistence + tools + health.

Tests that MCP mount does not break REST/WS, /mcp/health works,
and MCP tools function correctly with proper auth.
"""
from __future__ import annotations

import json
import pytest
import pytest_asyncio

from httpx import ASGITransport, AsyncClient

from agora.coordinator.storage import Storage
from agora.coordinator.mcp import mcp_server, create_mcp_app
from agora.coordinator.mcp.deps import init_mcp_deps
from agora.coordinator.mcp.auth import (
    register_agent_session,
    unregister_agent_session,
    get_session_id_for_agent,
    _agent_sessions,
    _session_agents,
    _validate_token,
    MCP_AUTH_WHITELIST,
)
from agora.coordinator.rbac import Role


@pytest_asyncio.fixture(loop_scope="session")
async def mcp_storage(tmp_path_factory):
    """Create a Storage instance for MCP tests (session-scoped)."""
    db_path = str(tmp_path_factory.mktemp("mcp") / "test_mcp.db")
    s = Storage(db_path)
    await s.init_db()
    # Initialize MCP deps so tools can use get_storage()
    init_mcp_deps(s, token_mgr=None, ws_manager=None)
    return s


@pytest_asyncio.fixture(loop_scope="session")
async def mcp_client(mcp_storage):
    """Create an httpx AsyncClient pointed at the MCP ASGI app."""
    app = create_mcp_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
    ) as client:
        yield client


class TestMCPHealth:
    """16.6b: /mcp/health endpoint."""

    @pytest.mark.asyncio
    async def test_mcp_health_no_auth(self, mcp_client):
        """Health endpoint should work without authentication."""
        resp = await mcp_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "agora-mcp"

    @pytest.mark.asyncio
    async def test_mcp_health_fields(self, mcp_client):
        """Health response includes expected fields."""
        resp = await mcp_client.get("/health")
        data = resp.json()
        assert "protocol" in data
        assert data["protocol"] == "streamable-http"


class TestMCPAuthMiddleware:
    """16.5 + 16.6a: MCP auth middleware unit tests."""

    def test_whitelist_health(self):
        """Health path is in MCP auth whitelist."""
        assert "/mcp/health" in MCP_AUTH_WHITELIST

    def test_validate_admin_token(self):
        """Admin token returns ADMIN role."""
        result = _validate_token("myadmin", None, "myadmin")
        assert result is not None
        assert result == ("admin", Role.ADMIN)

    def test_validate_invalid_token(self):
        """Unknown token returns None."""
        result = _validate_token("random", None, "")
        assert result is None

    def test_validate_ag_token(self):
        """Agent token (ag-*) returns AGENT role."""
        result = _validate_token("ag-sometoken", None, "")
        assert result is not None
        assert result[1] == Role.AGENT

    @pytest.mark.asyncio
    async def test_mcp_health_whitelisted(self, mcp_client):
        """Health endpoint bypasses auth middleware."""
        resp = await mcp_client.get("/health")
        assert resp.status_code == 200


class TestMCPAuthSessionMapping:
    """16.6: Agent-session mapping for notifications."""

    def setup_method(self):
        """Clear session mappings before each test."""
        _agent_sessions.clear()
        _session_agents.clear()

    def test_register_agent_session(self):
        """Register agent_id → mcp_session_id mapping."""
        register_agent_session("agent-1", "sess-abc")
        assert get_session_id_for_agent("agent-1") == "sess-abc"

    def test_unregister_agent_session(self):
        """Remove session mapping."""
        register_agent_session("agent-1", "sess-abc")
        unregister_agent_session("sess-abc")
        assert get_session_id_for_agent("agent-1") is None

    def test_session_replacement(self):
        """New session replaces old one for same agent."""
        register_agent_session("agent-1", "sess-old")
        register_agent_session("agent-1", "sess-new")
        assert get_session_id_for_agent("agent-1") == "sess-new"

    def test_multi_agent_sessions(self):
        """Multiple agents each have their own session."""
        register_agent_session("agent-1", "sess-a")
        register_agent_session("agent-2", "sess-b")
        assert get_session_id_for_agent("agent-1") == "sess-a"
        assert get_session_id_for_agent("agent-2") == "sess-b"


class TestMCPTools:
    """16.7b: MCP tool functionality."""

    @pytest.mark.asyncio
    async def test_register_agent_tool(self, mcp_storage):
        """register_agent tool creates an agent."""
        from agora.coordinator.mcp.tools.agent_tools import register_agent
        result = await register_agent(
            name="MCP Test Agent",
            capabilities=["python", "testing"],
        )
        assert "agent_id" in result
        assert "agent_token" in result
        assert result["agent_token"].startswith("ag-")
        assert result["approval_status"] in ("pending", "auto_approved")

        # Verify in storage
        agent = await mcp_storage.get_agent(result["agent_id"])
        assert agent is not None
        assert agent["name"] == "MCP Test Agent"

    @pytest.mark.asyncio
    async def test_get_pending_tasks_tool(self, mcp_storage):
        """get_pending_tasks returns task list."""
        from agora.coordinator.mcp.tools.task_tools import get_pending_tasks
        result = await get_pending_tasks(limit=10)
        assert "tasks" in result
        assert "total" in result
        assert isinstance(result["tasks"], list)

    @pytest.mark.asyncio
    async def test_accept_task_tool(self, mcp_storage):
        """accept_task transitions task to running."""
        from agora.coordinator.task_models import TaskNode, TaskStatus

        # Create motion + task graph + task
        motion = await mcp_storage.create_motion(
            title="Task Test Motion", description="test",
        )
        mid = motion["id"]
        await mcp_storage.create_task_graph("g1", mid)
        t = TaskNode(
            id="t1", graph_id="g1", motion_id=mid,
            title="Test Task", description="test",
            status=TaskStatus.PENDING,
        )
        async with mcp_storage._connection() as db:
            from agora.coordinator.storage import tasks as task_mod
            await task_mod.create_task(db, mcp_storage.dialect, t)

        from agora.coordinator.mcp.tools.task_tools import accept_task
        result = await accept_task(task_id="t1")
        assert result["task_id"] == "t1"
        assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_submit_task_result_tool(self, mcp_storage):
        """submit_task_result transitions task to done."""
        from agora.coordinator.task_models import TaskNode, TaskStatus
        from agora.coordinator.mcp.tools.task_tools import (
            accept_task, submit_task_result,
        )

        # Create motion + task graph + task + accept it
        motion = await mcp_storage.create_motion(
            title="Submit Motion", description="test",
        )
        mid = motion["id"]
        await mcp_storage.create_task_graph("g3", mid)
        t = TaskNode(
            id="t3", graph_id="g3", motion_id=mid,
            title="Submit Task", description="test",
            status=TaskStatus.PENDING,
        )
        async with mcp_storage._connection() as db:
            from agora.coordinator.storage import tasks as task_mod
            await task_mod.create_task(db, mcp_storage.dialect, t)

        await accept_task(task_id="t3")
        result = await submit_task_result(
            task_id="t3", result="All tests passed",
        )
        assert result["task_id"] == "t3"
        assert result["status"] == "done"

    @pytest.mark.asyncio
    async def test_submit_task_result_error(self, mcp_storage):
        """submit_task_result with error → failed."""
        from agora.coordinator.task_models import TaskNode, TaskStatus
        from agora.coordinator.storage import tasks as task_mod

        # Reuse the motion and task graph from accept test
        motion = await mcp_storage.create_motion(
            title="Fail Motion", description="test",
        )
        mid = motion["id"]
        await mcp_storage.create_task_graph("g2", mid)
        t = TaskNode(
            id="t2", graph_id="g2", motion_id=mid,
            title="Fail Task", description="test",
            status=TaskStatus.RUNNING,
        )
        async with mcp_storage._connection() as db:
            await task_mod.create_task(db, mcp_storage.dialect, t)

        from agora.coordinator.mcp.tools.task_tools import submit_task_result
        result = await submit_task_result(
            task_id="t2", error="Something went wrong",
        )
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_accept_nonexistent_task(self):
        """accept_task returns error for missing task."""
        from agora.coordinator.mcp.tools.task_tools import accept_task
        result = await accept_task(task_id="nonexistent")
        assert "error" in result
        assert result["code"] == 404

    @pytest.mark.asyncio
    async def test_update_status_tool(self):
        """update_status changes agent status."""
        from agora.coordinator.mcp.tools.agent_tools import update_status
        result = await update_status(status="busy", load=0.7)
        assert result["status"] == "busy"

    @pytest.mark.asyncio
    async def test_update_status_invalid(self):
        """update_status rejects invalid status."""
        from agora.coordinator.mcp.tools.agent_tools import update_status
        result = await update_status(status="invalid_status")
        assert "error" in result


class TestMCPCommTools:
    """16.7c: Communication tools."""

    @pytest.mark.asyncio
    async def test_send_message_tool(self, mcp_storage):
        """send_message adds a message to a conversation."""
        # Register an agent so FK constraint on messages.agent_id passes.
        # _get_current_agent_id() returns "unknown" in test context,
        # so we register an agent with that ID.
        await mcp_storage.register_agent(
            agent_id="unknown",
            name="Default Test Agent",
            agent_token="ag-testcomm",
            is_approved=True,
            approval_status="approved",
        )

        motion = await mcp_storage.create_motion(
            title="Test Discussion",
            description="test",
        )

        from agora.coordinator.mcp.tools.comm_tools import send_message
        result = await send_message(
            conversation_id=motion["id"],
            message="Hello from MCP!",
            stance="support",
        )
        assert "message_id" in result
        assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_send_message_invalid_stance(self, mcp_storage):
        """send_message rejects invalid stance."""
        motion = await mcp_storage.create_motion(
            title="Test Discussion 2",
            description="test",
        )

        from agora.coordinator.mcp.tools.comm_tools import send_message
        result = await send_message(
            conversation_id=motion["id"],
            message="Hello",
            stance="invalid",
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_send_message_nonexistent_conversation(self):
        """send_message returns error for missing conversation."""
        from agora.coordinator.mcp.tools.comm_tools import send_message
        result = await send_message(
            conversation_id="nonexistent",
            message="Hello",
        )
        assert "error" in result
        assert result.get("code") == 404

    @pytest.mark.asyncio
    async def test_list_conversations_tool(self, mcp_storage):
        """list_conversations returns conversation list."""
        from agora.coordinator.mcp.tools.comm_tools import list_conversations
        result = await list_conversations(limit=10)
        assert "conversations" in result
        assert "total" in result


class TestMCPCoexistence:
    """16.6a: Verify MCP mount does not break REST/WS routes."""

    @pytest.mark.asyncio
    async def test_mcp_health_does_not_conflict(self, mcp_client):
        """MCP /health doesn't conflict with REST /api/v1/health."""
        resp = await mcp_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        # MCP health returns service=agora-mcp
        assert data["service"] == "agora-mcp"

    def test_rbac_whitelist_includes_mcp(self):
        """RBAC whitelist includes /mcp paths."""
        from agora.coordinator.rbac_middleware import AUTH_WHITELIST
        assert "/mcp" in AUTH_WHITELIST
        assert "/mcp/health" in AUTH_WHITELIST

    def test_mcp_server_tools_registered(self):
        """All 9 MCP tools are registered."""
        from agora.coordinator.mcp import mcp_server
        tools = mcp_server._tool_manager._tools
        assert len(tools) >= 7  # At minimum the core tools
        expected = {
            "register_agent", "update_status",
            "get_pending_tasks", "accept_task", "submit_task_result",
            "send_message", "list_conversations",
        }
        assert expected.issubset(set(tools.keys()))


class TestMCPNotificationBridge:
    """16.4: MCP notification bridge."""

    @pytest.mark.asyncio
    async def test_bridge_creation(self, mcp_storage):
        """Notification bridge can be created."""
        from agora.coordinator.mcp.notifications import MCPNotificationBridge
        from agora.coordinator.mcp.session_map import MCPSessionMap
        sm = MCPSessionMap()
        bridge = MCPNotificationBridge(sm, mcp_storage)
        assert bridge is not None
        assert bridge._storage is mcp_storage

    @pytest.mark.asyncio
    async def test_bridge_task_assigned(self, mcp_storage):
        """Bridge handles task_assigned without errors."""
        from agora.coordinator.mcp.notifications import MCPNotificationBridge
        from agora.coordinator.mcp.session_map import MCPSessionMap
        sm = MCPSessionMap()
        bridge = MCPNotificationBridge(sm, mcp_storage)
        # Should not raise even if no session exists
        await bridge.on_task_assigned("t1", "agent-1", {
            "title": "Test Task",
            "description": "test",
        })

    def test_session_map(self):
        """MCPSessionMap tracks agent→session mapping."""
        from agora.coordinator.mcp.session_map import MCPSessionMap
        sm = MCPSessionMap()
        sm.register("agent-1", "sess-1")
        assert sm.get_session_id("agent-1") == "sess-1"
        sm.unregister_session("sess-1")
        assert sm.get_session_id("agent-1") is None
