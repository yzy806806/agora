"""Tests for Task Assigner — capability matching and assignment.

Phase 16.10: _send_task_assignment renamed to _notify_task_assignment.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from agora.coordinator.task_assign import (
    assign_tasks, capability_match_score,
    _find_capable_agents, _round_robin_pick, _notify_task_assignment,
    DEFAULT_MAX_CONCURRENT,
)
from agora.coordinator.task_models import TaskGraph, TaskNode, TaskStatus


def _make_agent(aid, caps, online=True):
    caps_json = json.dumps(caps) if isinstance(caps, list) else caps
    return {"agent_id": aid, "capabilities": caps_json, "is_online": online}


def _make_graph(tasks):
    return TaskGraph(id="g1", motion_id="m1", tasks=tasks)


# --- capability_match_score ---

def test_score_exact_match():
    assert capability_match_score(["code", "test"], ["code", "test"]) == 1.0


def test_score_partial_match():
    assert capability_match_score(["code"], ["code", "test"]) == 0.5


def test_score_no_match():
    assert capability_match_score(["docs"], ["code", "test"]) == 0.0


def test_score_no_requirements():
    assert capability_match_score(["code"], []) == 0.5


# --- _round_robin_pick ---

def test_rr_picks_first():
    cs = [_make_agent("a1", []), _make_agent("a2", [])]
    assert _round_robin_pick(cs, {}, {}, [0]) == "a1"


def test_rr_skips_at_capacity():
    cs = [_make_agent("a1", []), _make_agent("a2", [])]
    result = _round_robin_pick(cs, {"a1": 5}, {"a1": 5}, [0])
    assert result == "a2"


def test_rr_none_when_all_full():
    cs = [_make_agent("a1", [])]
    assert _round_robin_pick(cs, {"a1": 5}, {"a1": 5}, [0]) is None


def test_rr_none_empty_candidates():
    assert _round_robin_pick([], {}, {}, [0]) is None


# --- assign_tasks integration ---

@pytest.mark.asyncio
async def test_assign_basic():
    t1 = TaskNode(id="t1", graph_id="g1", motion_id="m1", title="T1",
                   required_capabilities=["code"])
    graph = _make_graph([t1])
    storage = AsyncMock()
    storage.list_agents.return_value = [_make_agent("a1", ["code"])]
    storage.get_agent_task_count.return_value = 0
    hub = MagicMock()
    hub.get_online_agents.return_value = ["a1"]
    hub.send = AsyncMock(return_value=True)
    result = await assign_tasks(graph, storage, hub)
    assert result == {"t1": "a1"}
    storage.update_task_status.assert_called_once_with(
        "t1", "assigned", assigned_to="a1")


@pytest.mark.asyncio
async def test_assign_deps_order():
    t1 = TaskNode(id="t1", graph_id="g1", motion_id="m1", title="T1",
                   required_capabilities=["code"])
    t2 = TaskNode(id="t2", graph_id="g1", motion_id="m1", title="T2",
                   required_capabilities=["code"], depends_on=["t1"])
    graph = _make_graph([t1, t2])
    storage = AsyncMock()
    storage.list_agents.return_value = [_make_agent("a1", ["code"])]
    storage.get_agent_task_count.return_value = 0
    hub = MagicMock()
    hub.get_online_agents.return_value = ["a1"]
    hub.send = AsyncMock(return_value=True)
    result = await assign_tasks(graph, storage, hub)
    assert result == {"t1": "a1", "t2": "a1"}


@pytest.mark.asyncio
async def test_assign_no_agent_skips():
    t1 = TaskNode(id="t1", graph_id="g1", motion_id="m1", title="T1",
                   required_capabilities=["security"])
    graph = _make_graph([t1])
    storage = AsyncMock()
    storage.list_agents.return_value = [_make_agent("a1", ["code"])]
    hub = MagicMock()
    hub.get_online_agents.return_value = ["a1"]
    result = await assign_tasks(graph, storage, hub)
    assert result == {}


# --- _notify_task_assignment ---

@pytest.mark.asyncio
async def test_notify_assignment_via_hub():
    task = TaskNode(id="t1", graph_id="g1", motion_id="m1", title="T",
                     required_capabilities=["code"])
    hub = MagicMock()
    hub.send = AsyncMock(return_value=True)
    assert await _notify_task_assignment(task, "a1", hub) is True
    hub.send.assert_called_once()
    msg = hub.send.call_args[0][1]
    assert msg["type"] == "TASK_ASSIGNED"
    assert msg["task_id"] == "t1"


@pytest.mark.asyncio
async def test_notify_assignment_via_mcp():
    """When hub is None, notification goes via event bus (MCP)."""
    task = TaskNode(id="t1", graph_id="g1", motion_id="m1", title="T",
                     required_capabilities=["code"])
    result = await _notify_task_assignment(task, "a1", hub=None)
    assert result is True
