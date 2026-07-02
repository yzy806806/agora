"""Tests for agora.discussion.chair prompt formatting."""
from __future__ import annotations

from agora.discussion.chair import (
    CHAIR_OPENING_PROMPT,
    build_speaker_prompt,
    build_vote_prompt,
)


def test_chair_opening_prompt():
    """CHAIR_OPENING_PROMPT.format() contains expected substrings."""
    output = CHAIR_OPENING_PROMPT.format(
        title="Test Topic",
        description="A test",
        participants="alice, bob",
        task_context="none",
    )
    assert "Test Topic" in output
    assert "A test" in output
    assert "alice, bob" in output
    assert "next_speaker" in output


def test_build_speaker_prompt():
    """build_speaker_prompt output contains role, title, and DISCUSSION_REPLY."""
    output = build_speaker_prompt(
        role="alice",
        title="Test",
        description="Desc",
        discussion_history="(none)",
        guidance="What do you think?",
        task_context="",
    )
    assert "alice" in output
    assert "Test" in output
    assert "DISCUSSION_REPLY" in output


def test_build_vote_prompt():
    """build_vote_prompt output contains role, title, JSON, and vote."""
    output = build_vote_prompt(
        role="alice",
        title="Test",
        discussion_history="some history",
    )
    assert "alice" in output
    assert "Test" in output
    assert "JSON" in output
    assert "vote" in output
