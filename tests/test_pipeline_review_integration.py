"""Tests for pipeline_review.py: collect_changed_files,
dispatch_review_request, build_fix_tasks."""
import pytest
from unittest.mock import AsyncMock

from agora.coordinator.pipeline_review import (
    collect_changed_files, dispatch_review_request, build_fix_tasks,
)
from agora.coordinator.pipeline_review import (
    ReviewIssue, ReviewRequest, ReviewResult,
)


@pytest.mark.asyncio
async def test_collect_changed_files():
    """Collect deduped artifact_paths from done tasks."""
    storage = AsyncMock()
    storage.list_tasks = AsyncMock(return_value=[
        {"artifact_paths": ["a.py", "b.py"]},
        {"artifact_paths": ["b.py", "c.py"]},
        {"artifact_paths": []},
    ])
    files = await collect_changed_files(storage, "graph-1")
    assert files == ["a.py", "b.py", "c.py"]
    storage.list_tasks.assert_called_once_with(
        graph_id="graph-1", status="done",
    )


@pytest.mark.asyncio
async def test_collect_changed_files_empty():
    """No done tasks returns empty list."""
    storage = AsyncMock()
    storage.list_tasks = AsyncMock(return_value=[])
    files = await collect_changed_files(storage, "graph-1")
    assert files == []


@pytest.mark.asyncio
async def test_dispatch_review_request():
    """Dispatches REVIEW_REQUEST via hub.send."""
    hub = AsyncMock()
    hub.send = AsyncMock(return_value=True)
    req = ReviewRequest(pipeline_id="p1", changed_files=["a.py"])
    result = await dispatch_review_request(hub, "reviewer-1", req)
    assert result is True
    msg = hub.send.call_args[0][1]
    assert msg["type"] == "REVIEW_REQUEST"


@pytest.mark.asyncio
async def test_dispatch_review_request_fail():
    """Returns False when hub.send fails."""
    hub = AsyncMock()
    hub.send = AsyncMock(return_value=False)
    req = ReviewRequest(pipeline_id="p1")
    assert await dispatch_review_request(hub, "r1", req) is False


def test_build_fix_tasks():
    """Creates fix task dicts from ReviewResult issues."""
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
    tasks = build_fix_tasks(result)
    assert len(tasks) == 2
    assert tasks[0]["type"] == "fix"
    assert tasks[0]["file"] == "a.py"
    assert tasks[0]["reviewer_id"] == "r1"
    assert tasks[1]["file"] == "b.py"
