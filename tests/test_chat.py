"""Tests for agora.chat — the 2.0 unified team channel.

These exercise the chat bus against a real (isolated) kanban board: chat-root
creation/parking, worker subscriptions, structured message posting, and the
per-worker unseen-message cursor. They never touch the real ~/.hermes kanban —
each test uses its own board slug and cleans up its rows.
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

import pytest


# The kanban_compat bridge emits FutureWarnings on the old import path; tests
# exercise the new submodule paths directly, so silence those.
warnings.filterwarnings("ignore", category=FutureWarning)

from hermes_plugins.agora.agora.kanban_compat import kanban_db as kb  # noqa: E402
from hermes_plugins.agora.agora import chat  # noqa: E402


@pytest.fixture()
def chat_conn(tmp_path, board_connection):
    """A kanban connection on a unique board, with cleanup of its rows."""
    board = f"agora2-test-{os.getpid()}-{tmp_path.name}"
    conn = board_connection(board)
    yield conn, board
    try:
        conn.execute("DELETE FROM tasks WHERE tenant = ?", (board,))
        conn.execute("DELETE FROM kanban_notify_subs WHERE task_id IN (SELECT id FROM tasks WHERE tenant = ?)", (board,))
        conn.commit()
    finally:
        conn.close()


def test_chat_root_is_scheduled_and_idempotent(chat_conn):
    conn, board = chat_conn
    root = chat.ensure_chat_root(conn, project_name="demo", tenant=board, created_by="leader")
    t = kb.get_task(conn, root)
    assert t is not None
    assert t.status == "scheduled", "chat root must be parked (not dispatchable)"

    again = chat.ensure_chat_root(conn, project_name="demo", tenant=board, created_by="leader")
    assert again == root, "ensure_chat_root must be idempotent via idempotency_key"


def test_post_and_read_messages(chat_conn):
    conn, board = chat_conn
    root = chat.ensure_chat_root(conn, project_name="demo", tenant=board)

    chat.post_message(conn, root_id=root, author="developer", msg_type="progress", content="done with mux")
    chat.post_message(conn, root_id=root, author="reviewer", msg_type="mention", content="interface changed", target="architect")

    msgs = chat.read_recent(conn, root_id=root, worker="architect", limit=10)
    assert len(msgs) == 2
    assert msgs[0]["type"] == "progress"
    assert msgs[0]["author"] == "developer"
    assert msgs[1]["type"] == "mention"
    assert msgs[1]["target"] == "architect"


def test_unseen_cursor_per_worker(chat_conn):
    conn, board = chat_conn
    root = chat.ensure_chat_root(conn, project_name="demo", tenant=board)
    for w in ("architect", "developer", "reviewer"):
        chat.subscribe_worker(conn, root_id=root, worker=w)

    # Three messages; everyone pulls all three on first read.
    for i in range(3):
        chat.post_message(conn, root_id=root, author="developer", msg_type="progress", content=f"msg {i}")

    for w in ("architect", "developer", "reviewer"):
        old, new, n = chat.pull_unseen(conn, root_id=root, worker=w)
        assert n == 3, f"{w} should see 3 new messages, got {n}"

    # One more message; only that one is unseen.
    chat.post_message(conn, root_id=root, author="tester", msg_type="progress", content="final")
    for w in ("architect", "developer", "reviewer"):
        old, new, n = chat.pull_unseen(conn, root_id=root, worker=w)
        assert n == 1, f"{w} should see 1 new message, got {n}"


def test_message_type_validation(chat_conn):
    conn, board = chat_conn
    root = chat.ensure_chat_root(conn, project_name="demo", tenant=board)

    with pytest.raises(ValueError):
        chat.post_message(conn, root_id=root, author="x", msg_type="bogus", content="bad")
    with pytest.raises(ValueError):
        chat.post_message(conn, root_id=root, author="x", msg_type="mention", content="no target")


def test_parse_message_skips_non_chat(chat_conn):
    conn, board = chat_conn
    root = chat.ensure_chat_root(conn, project_name="demo", tenant=board)

    chat.post_message(conn, root_id=root, author="dev", msg_type="progress", content="real message")
    # A plain (non-chat) comment must be ignored by parse_message.
    kb.add_comment(conn, root, author="dev", body="just a normal comment")

    msgs = chat.read_recent(conn, root_id=root, worker="dev", limit=10)
    assert len(msgs) == 1, "non-[agora:msg] comments must be filtered out"


def test_rewind_unseen_retries_delivery(chat_conn):
    conn, board = chat_conn
    root = chat.ensure_chat_root(conn, project_name="demo", tenant=board)
    chat.subscribe_worker(conn, root_id=root, worker="w1")

    chat.post_message(conn, root_id=root, author="a", msg_type="progress", content="one")

    old, new, n = chat.pull_unseen(conn, root_id=root, worker="w1")
    assert n == 1

    # Simulate a failed delivery: rewind the cursor, then re-claim.
    chat.rewind_unseen(conn, root_id=root, worker="w1", old_cursor=old, claimed_cursor=new)
    _, _, n2 = chat.pull_unseen(conn, root_id=root, worker="w1")
    assert n2 == 1, "rewound message must be re-claimable"
