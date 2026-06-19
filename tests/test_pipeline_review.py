"""Tests for pipeline_review_models: ReviewIssue, ReviewRequest, ReviewResult, PipelineRetryPolicy."""

import pytest

from agora.coordinator.pipeline_review import (
    ReviewIssue, ReviewRequest, ReviewResult,
)
from agora.coordinator.pipeline_models import PipelineRetryPolicy


# --- ReviewIssue tests ---

def test_issue_minimal():
    """ReviewIssue with required fields only."""
    issue = ReviewIssue(file="src/main.py", severity="major", description="bad code")
    assert issue.file == "src/main.py"
    assert issue.line is None
    assert issue.severity == "major"


def test_issue_with_line():
    """ReviewIssue with optional line number."""
    issue = ReviewIssue(file="a.py", line=42, severity="critical", description="x")
    assert issue.line == 42


def test_issue_invalid_severity():
    """Invalid severity raises ValidationError."""
    with pytest.raises(Exception):
        ReviewIssue(file="a.py", severity="high", description="x")


# --- ReviewRequest tests ---

def test_request_defaults():
    """ReviewRequest has empty defaults for lists/dicts."""
    req = ReviewRequest(pipeline_id="p1")
    assert req.changed_files == []
    assert req.task_results == []
    assert req.test_results == {}


def test_request_full():
    """ReviewRequest with all fields populated."""
    req = ReviewRequest(
        pipeline_id="p1",
        changed_files=["a.py", "b.py"],
        task_results=[{"task": "t1"}],
        test_results={"passed": 10},
    )
    assert len(req.changed_files) == 2


# --- ReviewResult tests ---

def test_result_approved():
    """ReviewResult with approved outcome."""
    r = ReviewResult(pipeline_id="p1", reviewer_id="rev1",
                     outcome="approved", summary="LGTM")
    assert r.issues == []
    assert r.outcome == "approved"


def test_result_changes_requested():
    """ReviewResult with changes_requested and issues."""
    issue = ReviewIssue(file="a.py", line=5, severity="critical", description="bug")
    r = ReviewResult(
        pipeline_id="p1", reviewer_id="rev1",
        outcome="changes_requested", issues=[issue],
    )
    assert len(r.issues) == 1
    assert r.summary == ""


def test_result_invalid_outcome():
    """Invalid outcome raises ValidationError."""
    with pytest.raises(Exception):
        ReviewResult(pipeline_id="p1", reviewer_id="r1",
                     outcome="maybe", summary="")


# --- PipelineRetryPolicy tests ---

def test_policy_defaults():
    """Default retry policy matches design spec."""
    p = PipelineRetryPolicy()
    assert p.max_retries == 3
    assert p.retry_delay == 30
    assert "executing" in p.retryable_phases
    assert "reviewing" in p.retryable_phases
    assert "releasing" in p.retryable_phases


def test_policy_custom():
    """Retry policy can be customized."""
    p = PipelineRetryPolicy(max_retries=5, retry_delay=10,
                            retryable_phases={"executing"})
    assert p.max_retries == 5
    assert len(p.retryable_phases) == 1
