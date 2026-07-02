"""Tests for agora.discussion.agent_spawn._extract_reply."""
from __future__ import annotations

from agora.discussion.agent_spawn import _extract_reply


def test_extract_reply_with_marker():
    """Input with DISCUSSION_REPLY: marker → returns the content after it."""
    text = "some text\nDISCUSSION_REPLY: My reply content\n"
    result = _extract_reply(text)
    assert result == "My reply content"


def test_extract_reply_without_marker():
    """Input without the marker → returns empty string."""
    result = _extract_reply("just some text")
    assert result == ""


def test_extract_reply_with_trailing_session_id():
    """Trailing session_id line should be stripped from the reply."""
    text = "DISCUSSION_REPLY: My reply\nsession_id: abc123"
    result = _extract_reply(text)
    assert result == "My reply"


def test_extract_reply_empty():
    """Empty input → returns empty string."""
    result = _extract_reply("")
    assert result == ""
