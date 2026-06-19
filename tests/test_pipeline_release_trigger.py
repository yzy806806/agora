"""Tests for trigger_release (consolidated, simplified).

Release auto-completes; no agent dispatch or error raising.
"""
from __future__ import annotations

import pytest

from agora.coordinator.pipeline_release import trigger_release


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
