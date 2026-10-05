"""Tests for agora.storage.motions_kanban — the Kanban-backed motions API shim.

Verifies the shim exposes the full 1.x motions API surface that the discussion
driver depends on (get_motion, add_message/get_messages, add_vote/get_votes,
discussion_state, increment_step_count, update_motion_status), backed by Kanban.
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

import pytest


warnings.filterwarnings("ignore", category=FutureWarning)

from hermes_plugins.agora.agora.kanban_compat import kanban_db as kb  # noqa: E402
from hermes_plugins.agora.agora import chat  # noqa: E402
from hermes_plugins.agora.agora.storage import motions_kanban as db  # noqa: E402


@pytest.fixture()
def kanban_env(tmp_path, monkeypatch):
    """Isolate the kanban board and clean up after.

    ``HERMES_KANBAN_DB`` is set by the conftest autouse fixture to a per-test-run
    temp file. We do NOT set ``HERMES_KANBAN_BOARD`` here: in newer Hermes the
    ``board`` parameter to ``connect()`` resolves to a per-board path
    (``<root>/kanban/boards/<board>/kanban.db``) that bypasses
    ``HERMES_KANBAN_DB`` entirely. The plugin's own ``_conn()`` calls
    ``connect()`` with no arguments, so it follows ``HERMES_KANBAN_DB``. Using
    ``connect(board=…)`` in the fixture would open a *different* database from
    the one the plugin code writes to — which is exactly why parent task
    lookups failed after the upstream change.

    Instead we open the same database the plugin uses (``connect()`` with no
    arguments) and use ``board`` purely as the ``tenant`` value for task
    isolation.
    """
    board = f"agora2-shim-{os.getpid()}-{tmp_path.name}"
    conn = kb.connect()
    yield conn, board
    try:
        conn.execute("DELETE FROM tasks WHERE tenant = ?", (board,))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def chat_root(kanban_env):
    conn, board = kanban_env
    root = chat.ensure_chat_root(conn, project_name="demo", tenant=board)
    return conn, board, root


def test_create_motion_returns_view(chat_root):
    conn, board, root = chat_root
    m = db.create_motion(
        title="SQLite or Postgres?",
        description="choosing a db",
        participants=["architect", "developer", "reviewer"],
        chair="leader",
        project="demo",
        chat_root_id=root,
    )
    assert m is not None
    assert m["id"]
    assert m["title"] == "SQLite or Postgres?"
    assert m["participants"] == ["architect", "developer", "reviewer"]
    assert m["chair"] == "leader"


def test_add_and_get_messages_field_mapping(chat_root):
    conn, board, root = chat_root
    m = db.create_motion(title="t", participants=["a", "b"], chair="leader", project="demo", chat_root_id=root)
    mid = m["id"]

    db.add_message(mid, role="a", round_num=1, stance="support", content="I support", step_type="speak")
    db.add_message(mid, role="leader", round_num=1, stance="neutral", content="keep going", step_type="guidance", is_chair=True)

    msgs = db.get_messages(mid)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "a"
    assert msgs[0]["step_type"] == "speak"
    assert msgs[0]["is_chair"] is False
    assert msgs[1]["is_chair"] is True
    assert msgs[1]["step_type"] == "guidance"


def test_votes_field_mapping(chat_root):
    conn, board, root = chat_root
    m = db.create_motion(title="t", participants=["a", "b"], chair="leader", project="demo", chat_root_id=root)
    mid = m["id"]

    db.add_vote(mid, role="a", vote="adopt", reason="good")
    db.add_vote(mid, role="b", vote="reject")

    votes = db.get_votes(mid)
    assert len(votes) == 2
    assert votes[0]["vote"] == "adopt"  # shim maps value→vote
    assert votes[0]["reason"] == "good"
    assert votes[1]["vote"] == "reject"


def test_discussion_state_roundtrip(chat_root):
    conn, board, root = chat_root
    m = db.create_motion(title="t", participants=["a"], chair="leader", project="demo", chat_root_id=root)
    mid = m["id"]

    db.save_discussion_state(mid, "discussing", next_speaker="a", last_guidance="go", last_action="continue")
    st = db.get_discussion_state(mid)
    assert st is not None
    assert st["current_state"] == "discussing"  # 1.x field name
    assert st["next_speaker"] == "a"
    assert st["last_guidance"] == "go"

    # increment_step_count works
    assert db.increment_step_count(mid) == 1
    assert db.increment_step_count(mid) == 2


def test_update_motion_status_closes(chat_root):
    conn, board, root = chat_root
    m = db.create_motion(title="t", participants=["a", "b"], chair="leader", project="demo", chat_root_id=root)
    mid = m["id"]

    db.add_message(mid, role="a", round_num=1, stance="support", content="x")
    db.update_motion_status(mid, status="closed", decision="adopted", rationale="1:0", action_items=["build"])

    closed = db.get_motion(mid)
    assert closed["status"] == "closed"  # shim maps kanban done → 1.x closed
    assert closed["decision"] == "adopted"
    assert closed["action_items"] == ["build"]


def test_list_motions(chat_root):
    conn, board, root = chat_root
    m1 = db.create_motion(title="one", participants=["a"], chair="l", project="demo", chat_root_id=root)
    m2 = db.create_motion(title="two", participants=["a"], chair="l", project="demo", chat_root_id=root)

    motions = db.list_motions(status_filter="all", chat_root_id=root)
    assert len(motions) == 2

    db.update_motion_status(m1["id"], status="closed", decision="rejected")
    closed = db.list_motions(status_filter="closed", chat_root_id=root)
    assert len(closed) == 1
    assert closed[0]["id"] == m1["id"]


def test_create_motion_preserves_source(chat_root):
    conn, board, root = chat_root
    m = db.create_motion(
        title="agent-raised", participants=["a"], chair="l",
        project="demo", chat_root_id=root, source="agent",
    )
    assert m["source"] == "agent"

    m2 = db.create_motion(title="user-raised", participants=["a"], chair="l", project="demo", chat_root_id=root)
    assert m2["source"] == "user"  # default
