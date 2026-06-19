"""Tests for Phase 16.4: SSE Notifications.

Tests the MCPNotificationBridge, MCPSessionMap, EventBus
forwarding, and mcp_sessions storage.
"""
import pytest

from agora.coordinator.mcp.session_map import MCPSessionMap
from agora.coordinator.mcp.notifications import MCPNotificationBridge
from agora.coordinator.storage import Storage


# --- MCPSessionMap tests ---


class TestMCPSessionMap:
    """Unit tests for the in-memory session mapping."""

    def test_register_and_lookup(self):
        sm = MCPSessionMap()
        sm.register("agent-1", "sess-abc")
        assert sm.get_session_id("agent-1") == "sess-abc"
        assert sm.get_agent_id("sess-abc") == "agent-1"

    def test_unregister_session(self):
        sm = MCPSessionMap()
        sm.register("agent-1", "sess-abc")
        sm.unregister_session("sess-abc")
        assert sm.get_session_id("agent-1") is None
        assert sm.get_agent_id("sess-abc") is None

    def test_agent_reconnects_new_session(self):
        """Latest session wins when agent reconnects."""
        sm = MCPSessionMap()
        sm.register("agent-1", "sess-old")
        sm.register("agent-1", "sess-new")
        assert sm.get_session_id("agent-1") == "sess-new"
        assert sm.get_agent_id("sess-old") is None

    def test_unregister_old_session_after_reconnect(self):
        sm = MCPSessionMap()
        sm.register("agent-1", "sess-old")
        sm.register("agent-1", "sess-new")
        sm.unregister_session("sess-old")
        assert sm.get_session_id("agent-1") == "sess-new"

    def test_is_agent_connected(self):
        sm = MCPSessionMap()
        assert not sm.is_agent_connected("agent-1")
        sm.register("agent-1", "sess-abc")
        assert sm.is_agent_connected("agent-1")

    def test_connected_agents(self):
        sm = MCPSessionMap()
        sm.register("a1", "s1")
        sm.register("a2", "s2")
        assert set(sm.connected_agents) == {"a1", "a2"}

    def test_session_count(self):
        sm = MCPSessionMap()
        assert sm.session_count == 0
        sm.register("a1", "s1")
        assert sm.session_count == 1

    def test_clear(self):
        sm = MCPSessionMap()
        sm.register("a1", "s1")
        sm.clear()
        assert sm.session_count == 0

    def test_lookup_nonexistent(self):
        sm = MCPSessionMap()
        assert sm.get_session_id("nope") is None
        assert sm.get_agent_id("nope") is None


# --- Fake MCP server for notification tests ---


class _FakeSession:
    def __init__(self):
        self.notifications: list[tuple[str, dict]] = []

    async def send_notification(self, method: str, params: dict):
        self.notifications.append((method, params))


class _FakeSessionManager:
    def __init__(self):
        self.sessions: dict[str, _FakeSession] = {}

    def add_session(self, session_id: str):
        self.sessions[session_id] = _FakeSession()


class _FakeServer:
    """Fake MCP server that records sent notifications."""

    def __init__(self):
        self.notifications: list[tuple[str, str, dict]] = []
        self._session_manager = _FakeSessionManager()


# --- MCPNotificationBridge tests ---


class TestMCPNotificationBridge:
    """Unit tests for the notification bridge."""

    @pytest.fixture
    def session_map(self):
        return MCPSessionMap()

    @pytest.fixture
    def fake_server(self):
        return _FakeServer()

    @pytest.fixture
    def bridge(self, session_map, fake_server, storage):
        b = MCPNotificationBridge(session_map, storage)
        b.set_mcp_server(fake_server)
        return b

    @pytest.mark.asyncio
    async def test_task_assigned_sends_notification(
        self, bridge, session_map, fake_server,
    ):
        session_map.register("agent-1", "sess-1")
        fake_server._session_manager.add_session("sess-1")
        await bridge.on_task_assigned(
            "task-42", "agent-1",
            {"title": "Fix bug", "priority": 1},
        )
        sess = fake_server._session_manager.sessions["sess-1"]
        assert len(sess.notifications) == 1
        method, params = sess.notifications[0]
        assert method == "notifications/task_assigned"
        assert params["task_id"] == "task-42"
        assert params["title"] == "Fix bug"

    @pytest.mark.asyncio
    async def test_task_assigned_no_session(
        self, bridge, session_map,
    ):
        """No error when agent has no MCP session."""
        await bridge.on_task_assigned(
            "task-42", "agent-offline", {},
        )

    @pytest.mark.asyncio
    async def test_task_updated_sends_notification(
        self, bridge, session_map, fake_server,
    ):
        session_map.register("agent-1", "sess-1")
        fake_server._session_manager.add_session("sess-1")
        await bridge.on_task_updated(
            "task-42", "assigned", "running", "agent-1",
        )
        sess = fake_server._session_manager.sessions["sess-1"]
        method, params = sess.notifications[0]
        assert method == "notifications/task_updated"
        assert params["old_status"] == "assigned"
        assert params["new_status"] == "running"

    @pytest.mark.asyncio
    async def test_discussion_message_skips_sender(
        self, bridge, session_map, fake_server,
    ):
        """Discussion messages are not echoed back to sender."""
        session_map.register("agent-1", "sess-1")
        session_map.register("agent-2", "sess-2")
        fake_server._session_manager.add_session("sess-1")
        fake_server._session_manager.add_session("sess-2")
        # Mock _get_conversation_participants to return both
        async def _mock_participants(conv_id):
            return ["agent-1", "agent-2"]
        bridge._get_conversation_participants = _mock_participants
        await bridge.on_discussion_message(
            "conv-1", "agent-1", "Hello world",
        )
        sess1 = fake_server._session_manager.sessions["sess-1"]
        sess2 = fake_server._session_manager.sessions["sess-2"]
        assert len(sess1.notifications) == 0  # sender skipped
        assert len(sess2.notifications) == 1
        assert sess2.notifications[0][0] == (
            "notifications/discussion_message"
        )

    @pytest.mark.asyncio
    async def test_pipeline_event_broadcasts_to_all(
        self, bridge, session_map, fake_server,
    ):
        session_map.register("a1", "s1")
        session_map.register("a2", "s2")
        fake_server._session_manager.add_session("s1")
        fake_server._session_manager.add_session("s2")
        await bridge.on_pipeline_event(
            "pipe-1", "build", "success", "Build passed",
        )
        for sid in ("s1", "s2"):
            sess = fake_server._session_manager.sessions[sid]
            assert len(sess.notifications) == 1
            assert sess.notifications[0][0] == (
                "notifications/pipeline_event"
            )

    @pytest.mark.asyncio
    async def test_no_server_configured(self, session_map, storage):
        """Bridge works without MCP server (no-op)."""
        b = MCPNotificationBridge(session_map, storage)
        session_map.register("a1", "s1")
        await b.on_task_assigned("t1", "a1", {})

    @pytest.mark.asyncio
    async def test_send_to_agent_returns_bool(
        self, bridge, session_map, fake_server,
    ):
        session_map.register("agent-1", "sess-1")
        fake_server._session_manager.add_session("sess-1")
        result = await bridge._send_to_agent(
            "agent-1", "notifications/test", {"x": 1},
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_send_to_agent_no_session(
        self, bridge, session_map,
    ):
        result = await bridge._send_to_agent(
            "agent-offline", "notifications/test", {},
        )
        assert result is False


# --- EventBus MCP forwarding tests ---


class TestEventBusMCPForwarding:
    """Test that event_bus.publish forwards to MCP bridge."""

    @pytest.mark.asyncio
    async def test_task_assigned_forwarded(self, storage):
        from agora.coordinator.event_bus import (
            init_mcp_bridge, publish,
        )
        sm = MCPSessionMap()
        bridge = MCPNotificationBridge(sm, storage)
        init_mcp_bridge(bridge)
        sm.register("agent-1", "sess-1")
        await publish("TASK_ASSIGNED", {
            "task_id": "t1",
            "agent_id": "agent-1",
            "title": "Test task",
        }, channel="tasks")

    @pytest.mark.asyncio
    async def test_task_status_forwarded(self, storage):
        from agora.coordinator.event_bus import (
            init_mcp_bridge, publish,
        )
        sm = MCPSessionMap()
        bridge = MCPNotificationBridge(sm, storage)
        init_mcp_bridge(bridge)
        sm.register("agent-1", "sess-1")
        await publish("TASK_STATUS", {
            "task_id": "t1",
            "status": "done",
            "old_status": "running",
            "agent_id": "agent-1",
        }, channel="tasks")

    @pytest.mark.asyncio
    async def test_discussion_message_forwarded(self, storage):
        from agora.coordinator.event_bus import (
            init_mcp_bridge, publish,
        )
        sm = MCPSessionMap()
        bridge = MCPNotificationBridge(sm, storage)
        init_mcp_bridge(bridge)
        await publish("DISCUSSION_MESSAGE", {
            "conversation_id": "conv-1",
            "sender_id": "agent-1",
            "message": "Hello",
        }, channel="discussions")

    @pytest.mark.asyncio
    async def test_pipeline_event_forwarded(self, storage):
        from agora.coordinator.event_bus import (
            init_mcp_bridge, publish,
        )
        sm = MCPSessionMap()
        bridge = MCPNotificationBridge(sm, storage)
        init_mcp_bridge(bridge)
        await publish("PIPELINE_EVENT", {
            "pipeline_id": "p1",
            "stage": "build",
            "status": "success",
        }, channel="pipelines")

    @pytest.mark.asyncio
    async def test_unknown_event_ignored(self, storage):
        from agora.coordinator.event_bus import (
            init_mcp_bridge, publish,
        )
        sm = MCPSessionMap()
        bridge = MCPNotificationBridge(sm, storage)
        init_mcp_bridge(bridge)
        await publish("UNKNOWN_EVENT", {}, channel="test")


# --- MCP sessions storage tests ---


class TestMCPSessionStorage:
    """Test mcp_sessions table CRUD via Storage mixin."""

    @pytest.mark.asyncio
    async def test_upsert_and_get(self, storage):
        await storage.upsert_mcp_session("sess-1", "agent-1")
        row = await storage.get_mcp_session_by_agent("agent-1")
        assert row is not None
        assert row["mcp_session_id"] == "sess-1"
        assert row["agent_id"] == "agent-1"

    @pytest.mark.asyncio
    async def test_get_by_session_id(self, storage):
        await storage.upsert_mcp_session("sess-2", "agent-2")
        row = await storage.get_mcp_session_by_id("sess-2")
        assert row is not None
        assert row["agent_id"] == "agent-2"

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, storage):
        """Re-upserting same session_id updates the record."""
        await storage.upsert_mcp_session("sess-1", "agent-1")
        await storage.upsert_mcp_session("sess-1", "agent-1")
        row = await storage.get_mcp_session_by_id("sess-1")
        assert row is not None

    @pytest.mark.asyncio
    async def test_update_activity(self, storage):
        await storage.upsert_mcp_session("sess-1", "agent-1")
        await storage.update_mcp_session_activity("sess-1")
        row = await storage.get_mcp_session_by_id("sess-1")
        assert row is not None

    @pytest.mark.asyncio
    async def test_delete_session(self, storage):
        await storage.upsert_mcp_session("sess-1", "agent-1")
        await storage.delete_mcp_session("sess-1")
        row = await storage.get_mcp_session_by_id("sess-1")
        assert row is None

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, storage):
        row = await storage.get_mcp_session_by_agent("nope")
        assert row is None

    @pytest.mark.asyncio
    async def test_delete_stale_sessions(self, storage):
        """Stale session cleanup removes old sessions."""
        await storage.upsert_mcp_session("sess-old", "agent-1")
        count = await storage.delete_stale_mcp_sessions(
            timeout_seconds=0,
        )
        assert isinstance(count, int)
