"""Tests for pipeline_review_handler: parse_review_result,
process_incoming_review_result, register_fix_tasks."""
import pytest
from unittest.mock import AsyncMock

from agora.coordinator.pipeline_review import (
    parse_review_result, process_incoming_review_result,
    register_fix_tasks,
)
from agora.coordinator.pipeline_review import (
    ReviewIssue, ReviewResult,
)


def _approved_payload():
    return {
        "pipeline_id": "p1", "reviewer_id": "r1",
        "outcome": "approved", "issues": [], "summary": "LGTM",
    }


def _changes_payload():
    return {
        "pipeline_id": "p1", "reviewer_id": "r1",
        "outcome": "changes_requested",
        "issues": [
            {"file": "a.py", "line": 5, "severity": "critical",
             "description": "bug"},
            {"file": "b.py", "severity": "minor",
             "description": "style"},
        ],
        "summary": "Fix issues",
    }


def test_parse_review_result_approved():
    result = parse_review_result(_approved_payload())
    assert result.outcome == "approved"
    assert result.issues == []
    assert result.reviewer_id == "r1"


def test_parse_review_result_changes():
    result = parse_review_result(_changes_payload())
    assert result.outcome == "changes_requested"
    assert len(result.issues) == 2
    assert result.issues[0].file == "a.py"
    assert result.issues[1].line is None


@pytest.mark.asyncio
async def test_process_incoming_approved():
    result = ReviewResult(
        pipeline_id="p1", reviewer_id="r1",
        outcome="approved", issues=[], summary="ok",
    )
    storage = AsyncMock()
    ids = await process_incoming_review_result(result, storage)
    assert ids == []
    storage.create_task.assert_not_called()


@pytest.mark.asyncio
async def test_process_incoming_changes_requested():
    result = ReviewResult(
        pipeline_id="p1", reviewer_id="r1",
        outcome="changes_requested",
        issues=[
            ReviewIssue(file="a.py", severity="critical",
                        description="bug"),
        ],
    )
    storage = AsyncMock()
    storage.create_task = AsyncMock(
        side_effect=["fix-1"],
    )
    ids = await process_incoming_review_result(result, storage)
    assert ids == ["fix-1"]
    storage.create_task.assert_called_once()


@pytest.mark.asyncio
async def test_register_fix_tasks():
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
    storage = AsyncMock()
    storage.create_task = AsyncMock(
        side_effect=["fix-1", "fix-2"],
    )
    ids = await register_fix_tasks(result, storage)
    assert ids == ["fix-1", "fix-2"]
    assert storage.create_task.call_count == 2
