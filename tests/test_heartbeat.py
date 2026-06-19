"""Tests for coordinator/heartbeat.py.

Phase 16.10: HeartbeatManager no longer depends on ConnectionManager.
"""
import asyncio
import time
import pytest

from agora.coordinator.heartbeat import HeartbeatManager, AgentConnectionStatus


@pytest.fixture
def hb():
    """Create a HeartbeatManager (no ConnectionManager needed)."""
    return HeartbeatManager()


class TestAgentConnectionStatus:
    def test_enum_values(self):
        assert AgentConnectionStatus.ACTIVE == "active"
        assert AgentConnectionStatus.UNRESPONSIVE == "unresponsive"
        assert AgentConnectionStatus.OFFLINE == "offline"


class TestHandlePong:
    def test_clears_pending_ping(self, hb):
        hb.pending_pings["agent1"] = time.time()
        hb.handle_pong("agent1")
        assert "agent1" not in hb.pending_pings

    def test_resets_missed_count(self, hb):
        hb.missed_pings["agent1"] = 2
        hb.handle_pong("agent1")
        assert hb.missed_pings["agent1"] == 0


class TestMarkOffline:
    def test_sets_missed_to_three(self, hb):
        hb.mark_offline("agent1")
        assert hb.missed_pings["agent1"] == 3

    def test_clears_pending_ping(self, hb):
        hb.pending_pings["agent1"] = time.time()
        hb.mark_offline("agent1")
        assert "agent1" not in hb.pending_pings


class TestGetConnectionStatus:
    def test_active_when_no_misses(self, hb):
        assert hb.get_connection_status("agent1") == AgentConnectionStatus.ACTIVE

    def test_unresponsive_after_one_miss(self, hb):
        hb.missed_pings["agent1"] = 1
        assert hb.get_connection_status("agent1") == AgentConnectionStatus.UNRESPONSIVE

    def test_offline_after_three_misses(self, hb):
        hb.missed_pings["agent1"] = 3
        assert hb.get_connection_status("agent1") == AgentConnectionStatus.OFFLINE


class TestStartStop:
    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, hb):
        await hb.start_heartbeat(interval=999)
        assert hb._task is not None
        await hb.stop()
        assert hb._task is None
