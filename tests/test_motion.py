"""Tests for agora.motion — the 2.0 Kanban-backed structured discussion."""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

import pytest


warnings.filterwarnings("ignore", category=FutureWarning)

from hermes_plugins.agora.agora.kanban_compat import kanban_db as kb  # noqa: E402
from hermes_plugins.agora.agora import chat, motion  # noqa: E402


@pytest.fixture()
def conn(tmp_path, board_connection):
    board = f"agora2-test-{os.getpid()}-{tmp_path.name}"
    c = board_connection(board)
    yield c, board
    try:
        c.execute("DELETE FROM tasks WHERE tenant = ?", (board,))
        c.execute("DELETE FROM kanban_notify_subs WHERE task_id IN (SELECT id FROM tasks WHERE tenant = ?)", (board,))
        c.commit()
    finally:
        c.close()


@pytest.fixture()
def root(conn):
    c, board = conn
    return chat.ensure_chat_root(c, project_name="demo", tenant=board)


def test_create_and_get_motion(conn, root):
    c, board = conn
    mid = motion.create_motion(
        c, chat_root_id=root, title="SQLite or Postgres?",
        participants=["architect", "developer", "reviewer"], chair="leader", tenant=board,
    )
    m = motion.get_motion(c, mid)
    assert m is not None
    assert m["title"] == "SQLite or Postgres?"
    assert m["participants"] == ["architect", "developer", "reviewer"]
    assert m["chair"] == "leader"
    # Motion is a child of the chat root.
    assert mid in kb.child_ids(c, root)


def test_speech_and_vote_roundtrip(conn, root):
    c, board = conn
    mid = motion.create_motion(c, chat_root_id=root, title="t", participants=["a", "b"], chair="l", tenant=board)

    motion.add_speech(c, motion_id=mid, role="a", round_num=1, stance="support", content="I support")
    motion.add_speech(c, motion_id=mid, role="b", round_num=1, stance="oppose", content="I disagree")
    motion.add_vote(c, motion_id=mid, role="a", vote="adopt", reason="good")
    motion.add_vote(c, motion_id=mid, role="b", vote="reject")

    speeches = motion.get_speeches(c, mid)
    votes = motion.get_votes(c, mid)
    assert len(speeches) == 2
    assert len(votes) == 2
    assert speeches[0]["role"] == "a"
    assert speeches[1]["stance"] == "oppose"
    assert votes[0]["value"] == "adopt"


def test_close_writes_result_and_done(conn, root):
    c, board = conn
    mid = motion.create_motion(c, chat_root_id=root, title="t", participants=["a", "b"], chair="l", tenant=board)
    motion.add_speech(c, motion_id=mid, role="a", round_num=1, stance="support", content="x")

    motion.close_motion(c, motion_id=mid, decision="adopted", rationale="1:0", action_items=["build table"])

    m = motion.get_motion(c, mid)
    assert m["status"] == "done"
    assert m["decision"] == "adopted"
    assert m["rationale"] == "1:0"
    assert m["action_items"] == ["build table"]
    assert m["state"] == "closed"


def test_zero_step_adopted_guard(conn, root):
    c, board = conn
    mid = motion.create_motion(c, chat_root_id=root, title="empty", participants=["a", "b"], chair="l", tenant=board)

    motion.close_motion(c, motion_id=mid, decision="adopted")

    m = motion.get_motion(c, mid)
    assert m["decision"] == "error", "0-speech motion must not be adopted"


def test_next_speaker_scheduler():
    participants = ["architect", "developer", "reviewer"]
    # Round-robin.
    assert motion.next_speaker(participants, last_speaker="architect", history=[{"role": "architect"}]) == "developer"
    assert motion.next_speaker(participants, last_speaker="reviewer", history=[{"role": "architect"}]) == "architect"
    # Mention priority.
    assert motion.next_speaker(
        participants, last_speaker="architect",
        history=[{"role": "architect"}], mentions=["reviewer"],
    ) == "reviewer"
    # No last speaker → first participant.
    assert motion.next_speaker(participants, last_speaker=None, history=[]) == "architect"


def test_get_motion_non_dict_result_is_safe(conn, root):
    c, board = conn
    mid = motion.create_motion(c, chat_root_id=root, title="t", participants=["a"], chair="l", tenant=board)
    # Simulate a malformed task.result that is valid JSON but not a dict.
    c.execute("UPDATE tasks SET result='123' WHERE id=?", (mid,))
    c.commit()
    m = motion.get_motion(c, mid)
    assert m is not None
    assert m["decision"] == "", "non-dict result must not crash decision extraction"
