"""Tests for release models + trigger (consolidated)."""
from __future__ import annotations

import pytest

from agora.coordinator.pipeline_release import (
    ReleaseRequest, ReleaseResult, trigger_release,
)


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


class TestTriggerRelease:
    @pytest.mark.asyncio
    async def test_success(self):
        result = await trigger_release(
            None, {"id": "g1", "changed_files": ["a.py"]},
            "proj-1", "LGTM",
        )
        assert "g1" in result

    @pytest.mark.asyncio
    async def test_no_hub_needed(self):
        """Simplified mode: no hub or agent lookup required."""
        result = await trigger_release(
            None, {"id": "g2"}, "proj-2",
        )
        assert result == "release-g2"
