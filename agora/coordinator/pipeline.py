"""PipelineOrchestrator — drives the full-auto dev loop (Phase 13).

State machine:
  IDEA_RECEIVED -> DISCUSSING -> DECOMPOSING -> EXECUTING ->
  REVIEWING -> RELEASING -> COMPLETED

Any phase can transition to FAILED on non-retryable errors.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from agora.coordinator.pipeline_models import PipelinePhase, PipelineRun
from agora.coordinator.pipeline_review_models import PipelineRetryPolicy
from agora.coordinator.pipeline_errors import PipelineError
from agora.coordinator.pipeline_executor import execute_phases

logger = logging.getLogger(__name__)


def _new_run(idea: str, project_id: str) -> PipelineRun:
    """Create a new PipelineRun with a ULID-style id."""
    return PipelineRun(
        id=uuid.uuid4().hex[:16], project_id=project_id,
        idea=idea, phase=PipelinePhase.DISCUSSING,
    )


class PipelineOrchestrator:
    """Drives the full-auto dev loop from idea to release.

    Reuses all existing components — this is a conductor, not a new engine.
    """

    def __init__(
        self, storage: Any, hub: Any,
        bootstrap_engine: Any, parallel_coordinator: Any,
        retry_policy: Optional[PipelineRetryPolicy] = None,
        notification_manager: Any = None,
        workspace_manager: Any = None,
    ) -> None:
        self.storage = storage
        self.hub = hub
        self.bootstrap = bootstrap_engine
        self.parallel = parallel_coordinator
        self.retry_policy = retry_policy or PipelineRetryPolicy()
        self.notification_manager = notification_manager
        self.workspace_manager = workspace_manager
        self.pipelines: dict[str, PipelineRun] = {}

    async def run(self, idea: str, project_id: str) -> PipelineRun:
        """Execute the full pipeline for a user idea."""
        run = _new_run(idea, project_id)
        self.pipelines[run.id] = run
        try:
            await execute_phases(self, run)
        except PipelineError as exc:
            run.phase = PipelinePhase.FAILED
            run.error = str(exc)
            logger.error("Pipeline %s failed: %s", run.id, exc)
        except Exception as exc:
            run.phase = PipelinePhase.FAILED
            run.error = f"Unexpected: {exc}"
            logger.exception("Pipeline %s unexpected error", run.id)
        # Notify on failure (success notification is sent in executor)
        if run.phase == PipelinePhase.FAILED and self.notification_manager:
            try:
                await self.notification_manager.notify_pipeline_failed(
                    run.id, run.project_id, run.error or "unknown",
                )
            except Exception:
                logger.warning("Failed to send failure notification", exc_info=True)
        return run
