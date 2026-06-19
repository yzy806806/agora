"""Tests for pipeline_review.py (consolidated, simplified).

Auto-approves reviews; no agent dispatch.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from agora.coordinator.pipeline_review import (
    trigger_code_review, process_review_response,
    PipelineReviewer, ReviewResult, ReviewIssue,
    build_fix_tasks,
)


@pytest.mark.asyncio
async def test_trigger_review_auto_approve():
    """Auto-approves when no review agent is online."""
    hub = MagicMock()
    result = await trigger_code_review(hub, {"id": "g1"}, "proj-1")
    assert result.outcome == "approved"
    assert result.reviewer_id == "auto"


@pytest.mark.asyncio
async def test_trigger_review_with_agent_online():
    """Still auto-approves even when agent is online (simplified)."""
    hub = MagicMock()
    result = await trigger_code_review(hub, {"id": "g1"}, "proj-1")
    assert result.outcome == "approved"
    assert result.reviewer_id == "auto"


@pytest.mark.asyncio
async def test_trigger_review_with_storage():
    """Accepts storage param (ignored in simplified mode)."""
    hub = MagicMock()
    storage = AsyncMock()
    result = await trigger_code_review(
        hub, {"id": "g1"}, "proj-1", storage=storage,
    )
    assert result.outcome == "approved"


def test_process_review_approved():
    """Approved review returns no fix tasks."""
    result = ReviewResult(
        pipeline_id="p1", reviewer_id="r1",
        outcome="approved", summary="LGTM",
    )
    assert process_review_response(result) == []


def test_process_review_changes_requested():
    """Changes requested returns fix tasks."""
    result = ReviewResult(
        pipeline_id="p1", reviewer_id="r1",
        outcome="changes_requested",
        issues=[
            ReviewIssue(file="a.py", severity="critical",
                        description="bug"),
        ],
    )
    tasks = process_review_response(result)
    assert len(tasks) == 1
    assert tasks[0]["type"] == "fix"
    assert tasks[0]["file"] == "a.py"


def test_build_fix_tasks():
    """build_fix_tasks creates fix task dicts from issues."""
    result = ReviewResult(
        pipeline_id="p1", reviewer_id="r1",
        outcome="changes_requested",
        issues=[
            ReviewIssue(file="a.py", line=5, severity="critical",
                        description="bug"),
        ],
    )
    tasks = build_fix_tasks(result)
    assert len(tasks) == 1
    assert tasks[0]["file"] == "a.py"
    assert tasks[0]["line"] == 5
