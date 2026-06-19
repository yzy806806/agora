"""Unit tests for PipelineReviewer (consolidated, simplified).

Auto-approves; no agent dispatch.
"""
import pytest
from unittest.mock import AsyncMock

from agora.coordinator.pipeline_review import (
    PipelineReviewer, ReviewResult, ReviewIssue,
)


def _make_reviewer():
    hub = AsyncMock()
    return PipelineReviewer(hub)


@pytest.mark.asyncio
async def test_request_review():
    """request_review auto-approves (no agent dispatch)."""
    reviewer = _make_reviewer()
    result = await reviewer.request_review("p1", ["a.py", "b.py"])
    assert result.outcome == "approved"
    assert result.reviewer_id == "auto"


@pytest.mark.asyncio
async def test_process_review_approved():
    """Approved review returns no fix tasks."""
    reviewer = _make_reviewer()
    result = ReviewResult(
        pipeline_id="p1", reviewer_id="r1",
        outcome="approved", summary="ok",
    )
    tasks = await reviewer.process_review_result(result)
    assert tasks == []


@pytest.mark.asyncio
async def test_process_review_changes_requested():
    """Changes requested returns fix tasks for each issue."""
    reviewer = _make_reviewer()
    result = ReviewResult(
        pipeline_id="p1", reviewer_id="r1",
        outcome="changes_requested",
        issues=[
            ReviewIssue(file="a.py", line=5, severity="critical",
                        description="bug"),
            ReviewIssue(file="b.py", severity="minor",
                        description="style"),
        ],
    )
    tasks = await reviewer.process_review_result(result)
    assert len(tasks) == 2
    assert tasks[0]["type"] == "fix"
    assert tasks[0]["file"] == "a.py"
    assert tasks[1]["file"] == "b.py"


@pytest.mark.asyncio
async def test_re_review():
    """Re-review auto-approves (simplified)."""
    reviewer = _make_reviewer()
    result = await reviewer.re_review("p1", [
        {"file": "a.py"}, {"file": "b.py"},
    ])
    assert result.outcome == "approved"
    assert result.reviewer_id == "auto"
