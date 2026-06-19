"""Integration test: review changes_requested -> fix -> re-review cycle."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from agora.coordinator.pipeline_review import PipelineReviewer
from agora.coordinator.pipeline_review import (
    ReviewIssue, ReviewResult,
)


@pytest.mark.asyncio
async def test_review_fix_rereview_cycle():
    """Full cycle: review rejects -> fix tasks created -> re-review approves."""
    reviewer = PipelineReviewer(AsyncMock())

    # First review: changes requested
    first_result = ReviewResult(
        pipeline_id="p1", reviewer_id="r1",
        outcome="changes_requested",
        issues=[
            ReviewIssue(file="a.py", line=10, severity="critical",
                        description="SQL injection"),
        ],
        summary="Fix SQL injection",
    )
    fix_tasks = await reviewer.process_review_result(first_result)
    assert len(fix_tasks) == 1
    assert fix_tasks[0]["file"] == "a.py"

    # Simulate fixes applied, re-review
    second_result = ReviewResult(
        pipeline_id="p1", reviewer_id="r1",
        outcome="approved", summary="LGTM",
    )
    reviewer.hub.submit_review = AsyncMock(return_value=second_result)
    re_review = await reviewer.re_review("p1", fix_tasks)
    assert re_review.outcome == "approved"


@pytest.mark.asyncio
async def test_review_multiple_issues():
    """Review with multiple issues generates multiple fix tasks."""
    reviewer = PipelineReviewer(AsyncMock())
    result = ReviewResult(
        pipeline_id="p1", reviewer_id="r1",
        outcome="changes_requested",
        issues=[
            ReviewIssue(file="a.py", severity="critical", description="bug1"),
            ReviewIssue(file="b.py", severity="major", description="bug2"),
            ReviewIssue(file="c.py", severity="minor", description="style"),
        ],
    )
    tasks = await reviewer.process_review_result(result)
    assert len(tasks) == 3
    files = [t["file"] for t in tasks]
    assert files == ["a.py", "b.py", "c.py"]
