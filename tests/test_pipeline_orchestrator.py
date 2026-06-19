"""Unit tests for PipelineOrchestrator internals."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from agora.coordinator.pipeline import PipelineOrchestrator, _new_run
from agora.coordinator.pipeline_models import PipelinePhase


def test_new_run_defaults():
    """_new_run creates a PipelineRun in DISCUSSING phase."""
    run = _new_run("my idea", "proj-1")
    assert run.idea == "my idea"
    assert run.project_id == "proj-1"
    assert run.phase is PipelinePhase.DISCUSSING
    assert len(run.id) == 16


def test_new_run_unique_ids():
    """Each call to _new_run generates a different ID."""
    r1 = _new_run("a", "p")
    r2 = _new_run("a", "p")
    assert r1.id != r2.id


def test_orchestrator_stores_pipeline():
    """PipelineOrchestrator.run() stores the run in self.pipelines."""
    orch = PipelineOrchestrator(
        MagicMock(), MagicMock(), MagicMock(), MagicMock()
    )
    # Patch execute_phases to avoid full pipeline execution
    import agora.coordinator.pipeline_executor as pe
    original = pe.execute_phases
    pe.execute_phases = AsyncMock()

    import asyncio
    asyncio.get_event_loop().run_until_complete(orch.run("idea", "p"))
    assert len(orch.pipelines) == 1
    pe.execute_phases = original


def test_orchestrator_retry_policy_default():
    """Default retry policy is used when none provided."""
    from agora.coordinator.pipeline_models import PipelineRetryPolicy
    orch = PipelineOrchestrator(
        MagicMock(), MagicMock(), MagicMock(), MagicMock()
    )
    assert isinstance(orch.retry_policy, PipelineRetryPolicy)
    assert orch.retry_policy.max_retries == 3


def test_orchestrator_retry_policy_custom():
    """Custom retry policy is used when provided."""
    from agora.coordinator.pipeline_models import PipelineRetryPolicy
    policy = PipelineRetryPolicy(max_retries=5)
    orch = PipelineOrchestrator(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(),
        retry_policy=policy,
    )
    assert orch.retry_policy.max_retries == 5
