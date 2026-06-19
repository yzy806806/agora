"""Integration tests for the full pipeline lifecycle.

Tests end-to-end flows using the real PipelineOrchestrator +
execute_phases with mocked bootstrap/hub/parallel dependencies.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from agora.coordinator.pipeline import PipelineOrchestrator
from agora.coordinator.pipeline_errors import ExecutionFailedError
from agora.coordinator.pipeline_models import PipelinePhase
from agora.coordinator.pipeline_models import PipelineRetryPolicy
from agora.coordinator.bootstrap.discussion_driver import DiscussionResult


def _result(decision="adopted"):
    return DiscussionResult(
        motion_id="motion-1", decision=decision,
        recommended_actions=[{"title": "T1", "description": "d", "category": "dev"}],
    )


def _orch(decision="adopted", retry_delay=0):
    storage = MagicMock()
    hub = MagicMock()
    hub.get_online_agents.return_value = ["reviewer-1", "releaser-1"]
    hub.send = AsyncMock(return_value=True)
    bootstrap = MagicMock()
    bootstrap.discussion_driver = MagicMock()
    bootstrap.discussion_driver.start_dev_discussion = AsyncMock(return_value="motion-1")
    bootstrap.discussion_driver.wait_for_result = AsyncMock(return_value=_result(decision))
    bootstrap.task_generator = MagicMock()
    bootstrap.task_generator.from_discussion_result = AsyncMock(return_value=["task-1"])
    parallel = MagicMock()
    parallel.execute_graph = AsyncMock(return_value={"completed": ["task-1"], "failed": []})
    policy = PipelineRetryPolicy(max_retries=3, retry_delay=retry_delay)
    return PipelineOrchestrator(storage, hub, bootstrap, parallel, policy)


@pytest.mark.asyncio
async def test_full_pipeline_lifecycle():
    """E2E: discuss -> decompose -> execute -> review -> release -> completed."""
    orch = _orch()
    run = await orch.run("add auth", "proj1")
    assert run.phase == PipelinePhase.COMPLETED
    assert run.motion_id == "motion-1"
    assert run.tasks_total == 1
    assert run.tasks_completed == 1


@pytest.mark.asyncio
async def test_pipeline_discussion_rejected():
    """Pipeline fails when discussion is rejected."""
    orch = _orch(decision="rejected")
    run = await orch.run("bad idea", "p1")
    assert run.phase == PipelinePhase.FAILED
    assert run.error is not None


@pytest.mark.asyncio
async def test_pipeline_execution_failure():
    """Pipeline fails when execution phase errors out."""
    orch = _orch()
    orch.parallel.execute_graph = AsyncMock(
        side_effect=ExecutionFailedError("task crashed")
    )
    run = await orch.run("feature", "p1")
    assert run.phase == PipelinePhase.FAILED
