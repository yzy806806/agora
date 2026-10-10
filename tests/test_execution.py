"""Tests for agora.execution — the discussion↔execution converter."""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

import pytest


warnings.filterwarnings("ignore", category=FutureWarning)

from hermes_plugins.agora.agora.kanban_compat import kanban_db as kb  # noqa: E402
from hermes_plugins.agora.agora import chat, motion, execution  # noqa: E402


@pytest.fixture()
def conn(tmp_path, board_connection):
    board = f"agora2-test-{os.getpid()}-{tmp_path.name}"
    c = board_connection(board)
    yield c, board
    try:
        c.execute("DELETE FROM tasks WHERE tenant = ?", (board,))
        c.commit()
    finally:
        c.close()


@pytest.fixture()
def root(conn):
    c, board = conn
    return chat.ensure_chat_root(c, project_name="demo", tenant=board)


def test_motion_to_tasks_parent_handoff(conn, root):
    c, board = conn
    mid = motion.create_motion(c, chat_root_id=root, title="pick db", participants=["a", "b"], chair="l", tenant=board)
    motion.add_speech(c, motion_id=mid, role="a", round_num=1, stance="support", content="x")
    motion.close_motion(c, motion_id=mid, decision="adopted", rationale="ok", action_items=["build"])

    tasks = execution.motion_to_tasks(
        c, motion_id=mid, action_items=[{"item": "build table", "owner": "developer"}],
        title="pick db", tenant=board,
    )
    assert len(tasks) == 1
    assert kb.parent_ids(c, tasks[0]) == [mid], "execution task's parent must be the motion"


def test_motion_to_tasks_dependency_order(conn, root):
    c, board = conn
    mid = motion.create_motion(c, chat_root_id=root, title="t", participants=["a"], chair="l", tenant=board)
    items = [
        {"item": "step one", "owner": "developer"},
        {"item": "step two", "owner": "developer", "depends_on": [1]},
    ]
    tasks = execution.motion_to_tasks(c, motion_id=mid, action_items=items, title="t", tenant=board)
    assert len(tasks) == 2
    # Task 2 depends on task 1.
    assert kb.parent_ids(c, tasks[1]) == [tasks[0]]


def test_blocked_to_motion_context_bridge(conn, root):
    c, board = conn
    blk = kb.create_task(c, title="implement TLS", assignee="developer", tenant=board, initial_status="blocked")

    mid = execution.blocked_to_motion(c, task_id=blk, chat_root_id=root, tenant=board)

    m = motion.get_motion(c, mid)
    assert "developer" in m["participants"], "blocked task's assignee must join the discussion"
    parents = kb.parent_ids(c, mid)
    assert blk in parents, "motion must depend on the blocked task for context handoff"
    assert m["source_task_id"] == blk
