"""Tests for agora.discussion.driver.DiscussionDriver."""
from __future__ import annotations

from agora.discussion.driver import DiscussionDriver
from agora.utils import parse_json_response


def test_driver_init():
    """DiscussionDriver.__init__ sets all attributes correctly."""
    driver = DiscussionDriver(
        motion_id="test",
        chair_profile="leader",
        participants=["alice", "bob"],
        workdir="/tmp",
        project_name="test",
        max_steps=10,
    )
    assert driver.motion_id == "test"
    assert driver.chair_profile == "leader"
    assert driver.participants == ["alice", "bob"]
    assert driver.workdir == "/tmp"
    assert driver.project_name == "test"
    assert driver.max_steps == 10


def test_infer_stance():
    """_infer_stance returns support/oppose/neutral based on keyword counts."""
    driver = DiscussionDriver(
        motion_id="stub",
        chair_profile="leader",
        participants=["alice"],
    )

    # support=2 (agree, support), oppose=0 → 2 > 0+1 → "support"
    assert driver._infer_stance("I agree and support this approach") == "support"

    # "disagree" should NOT count as "agree" (word-boundary fix).
    # oppose=2 (disagree, oppose), support=0 → 2 > 0+1 → "oppose"
    assert driver._infer_stance("I disagree and oppose this") == "oppose"

    # support=0, oppose=0 → "neutral"
    assert driver._infer_stance("This is interesting") == "neutral"


def test_parse_json_response():
    """parse_json_response handles plain JSON, non-JSON, and fenced JSON."""
    # Plain JSON object
    result = parse_json_response('{"action": "continue"}')
    assert result is not None
    assert result["action"] == "continue"

    # Non-JSON text → None
    assert parse_json_response("not json") is None

    # Markdown-fenced JSON → parsed dict
    result = parse_json_response('```json\n{"x": 1}\n```')
    assert result is not None
    assert result["x"] == 1
