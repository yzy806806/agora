"""Tests for agora.storage.motions — the SQLite motions DB."""
from __future__ import annotations

from agora.storage import motions as db


# --------------------------------------------------------------------------- #
#  Motion CRUD                                                                #
# --------------------------------------------------------------------------- #

def test_create_and_get_motion(clean_db):
    """create_motion → get_motion, verify all fields."""
    motion = db.create_motion(
        title="Test Motion",
        description="A test description",
        participants=["alice", "bob"],
        chair="leader",
        max_steps=10,
    )
    assert motion is not None
    assert motion["id"].startswith("motion-")
    assert motion["title"] == "Test Motion"
    assert motion["description"] == "A test description"
    assert motion["status"] == "discussing"
    assert motion["participants"] == ["alice", "bob"]
    assert motion["chair"] == "leader"
    assert motion["state"] == "discussing"
    assert motion["step_count"] == 0
    assert motion["max_steps"] == 10

    # Round-trip: fetch it back from the DB
    fetched = db.get_motion(motion["id"])
    assert fetched is not None
    assert fetched["id"] == motion["id"]
    assert fetched["title"] == "Test Motion"
    assert fetched["description"] == "A test description"
    assert fetched["status"] == "discussing"
    assert fetched["participants"] == ["alice", "bob"]
    assert fetched["chair"] == "leader"
    assert fetched["state"] == "discussing"
    assert fetched["step_count"] == 0
    assert fetched["max_steps"] == 10


def test_list_motions(clean_db):
    """list_motions with status_filter active/closed/all."""
    m1 = db.create_motion(title="Active 1")
    m2 = db.create_motion(title="Active 2")
    m3 = db.create_motion(title="Closed 1")
    db.update_motion_status(m3["id"], status="closed")

    active = db.list_motions(status_filter="active")
    closed = db.list_motions(status_filter="closed")
    all_motions = db.list_motions(status_filter="all")

    assert len(active) == 2
    assert len(closed) == 1
    assert len(all_motions) == 3

    # The closed list should contain only m3
    closed_ids = [m["id"] for m in closed]
    assert m3["id"] in closed_ids

    # The active list should not contain m3
    active_ids = [m["id"] for m in active]
    assert m3["id"] not in active_ids


def test_update_motion_status(clean_db):
    """Close a motion with decision/rationale/action_items, verify updated fields."""
    motion = db.create_motion(title="Close Me")
    db.update_motion_status(
        motion["id"],
        status="closed",
        decision="adopted",
        rationale="test rationale",
        action_items=["item1", "item2"],
    )
    fetched = db.get_motion(motion["id"])
    assert fetched is not None
    assert fetched["status"] == "closed"
    assert fetched["decision"] == "adopted"
    assert fetched["rationale"] == "test rationale"
    assert fetched["action_items"] == ["item1", "item2"]
    assert fetched["closed_at"] is not None  # closed_at set on status="closed"


# --------------------------------------------------------------------------- #
#  Messages                                                                   #
# --------------------------------------------------------------------------- #

def test_add_and_get_messages(clean_db):
    """Add 3 messages to a motion, retrieve them, verify order and fields."""
    motion = db.create_motion(title="Message Test")

    db.add_message(motion["id"], "alice", round_num=1, stance="support",
                   content="I support this", step_type="speak")
    db.add_message(motion["id"], "bob", round_num=1, stance="oppose",
                   content="I disagree", step_type="speak")
    db.add_message(motion["id"], "leader", round_num=1, stance="neutral",
                   content="Let's continue", step_type="guidance",
                   is_chair=True)

    messages = db.get_messages(motion["id"])
    assert len(messages) == 3

    # Verify order (timestamp ASC)
    assert messages[0]["role"] == "alice"
    assert messages[1]["role"] == "bob"
    assert messages[2]["role"] == "leader"

    # Verify fields on the first message
    m0 = messages[0]
    assert m0["motion_id"] == motion["id"]
    assert m0["role"] == "alice"
    assert m0["round_num"] == 1
    assert m0["stance"] == "support"
    assert m0["content"] == "I support this"
    assert m0["step_type"] == "speak"
    assert m0["is_chair"] == 0  # SQLite stores bool as int

    # Verify chair flag on the last message
    assert messages[2]["is_chair"] == 1
    assert messages[2]["step_type"] == "guidance"


# --------------------------------------------------------------------------- #
#  Votes                                                                      #
# --------------------------------------------------------------------------- #

def test_add_and_get_votes(clean_db):
    """Add 2 votes to a motion, retrieve them, verify fields."""
    motion = db.create_motion(title="Vote Test")

    db.add_vote(motion["id"], "alice", vote="adopt", reason="Good plan",
                confidence=0.9)
    db.add_vote(motion["id"], "bob", vote="reject", reason="Risky",
                confidence=0.6)

    votes = db.get_votes(motion["id"])
    assert len(votes) == 2

    v0 = votes[0]
    assert v0["motion_id"] == motion["id"]
    assert v0["role"] == "alice"
    assert v0["vote"] == "adopt"
    assert v0["reason"] == "Good plan"
    assert v0["confidence"] == 0.9

    v1 = votes[1]
    assert v1["role"] == "bob"
    assert v1["vote"] == "reject"
    assert v1["reason"] == "Risky"
    assert v1["confidence"] == 0.6


# --------------------------------------------------------------------------- #
#  Discussion state                                                           #
# --------------------------------------------------------------------------- #

def test_discussion_state(clean_db):
    """save_discussion_state → get → update → verify fields."""
    motion = db.create_motion(title="State Test")

    # Initially no state
    assert db.get_discussion_state(motion["id"]) is None

    # Save initial state
    db.save_discussion_state(
        motion["id"],
        current_state="discussing",
        next_speaker="alice",
        last_guidance="What do you think?",
        last_action="continue",
    )
    state = db.get_discussion_state(motion["id"])
    assert state is not None
    assert state["motion_id"] == motion["id"]
    assert state["current_state"] == "discussing"
    assert state["next_speaker"] == "alice"
    assert state["last_guidance"] == "What do you think?"
    assert state["last_action"] == "continue"

    # Update state (upsert)
    db.save_discussion_state(
        motion["id"],
        current_state="voting",
        next_speaker="bob",
        last_guidance="Time to vote",
        last_action="vote",
    )
    state2 = db.get_discussion_state(motion["id"])
    assert state2 is not None
    assert state2["current_state"] == "voting"
    assert state2["next_speaker"] == "bob"
    assert state2["last_guidance"] == "Time to vote"
    assert state2["last_action"] == "vote"
    assert state2["updated_at"] is not None


# --------------------------------------------------------------------------- #
#  Step count                                                                 #
# --------------------------------------------------------------------------- #

def test_increment_step_count(clean_db):
    """create motion (step_count=0), increment twice, verify step_count=2."""
    motion = db.create_motion(title="Step Count Test")
    assert motion["step_count"] == 0

    count1 = db.increment_step_count(motion["id"])
    assert count1 == 1

    count2 = db.increment_step_count(motion["id"])
    assert count2 == 2

    fetched = db.get_motion(motion["id"])
    assert fetched is not None
    assert fetched["step_count"] == 2
