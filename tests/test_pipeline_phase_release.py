"""Tests for pipeline_release.py (consolidated, simplified).

Tests: trigger_release auto-completes, ReleaseRequest/Result models.
"""
import pytest

from agora.coordinator.pipeline_release import (
    trigger_release, ReleaseRequest, ReleaseResult,
)


@pytest.mark.asyncio
async def test_trigger_release_auto_complete():
    """Auto-completes release and returns release id."""
    result = await trigger_release(None, {"id": "g1"}, "proj-1")
    assert result == "release-g1"


@pytest.mark.asyncio
async def test_trigger_release_with_review_summary():
    """Accepts review_summary param (ignored in simplified mode)."""
    result = await trigger_release(
        None, {"id": "g2"}, "proj-2",
        review_summary="LGTM",
    )
    assert result == "release-g2"


@pytest.mark.asyncio
async def test_trigger_release_with_workspace_paths():
    """Accepts workspace_paths param (ignored in simplified mode)."""
    result = await trigger_release(
        None, {"id": "g3"}, "proj-3",
        workspace_paths=["/tmp/ws"],
    )
    assert result == "release-g3"


class TestReleaseModels:
    def test_release_request_defaults(self):
        r = ReleaseRequest(
            pipeline_id="p1", project_id="proj",
            graph_id="g1",
        )
        assert r.changed_files == []
        assert r.review_summary == ""

    def test_release_result_success(self):
        r = ReleaseResult(
            pipeline_id="p1", outcome="success",
            version="0.13.0", tag="v0.13.0",
        )
        assert r.version == "0.13.0"
        assert r.error is None

    def test_release_result_failure(self):
        r = ReleaseResult(
            pipeline_id="p1", outcome="failed",
            error="push rejected",
        )
        assert r.outcome == "failed"
        assert r.error == "push rejected"
