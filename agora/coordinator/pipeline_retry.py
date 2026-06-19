"""Pipeline retry logic with exponential backoff (Phase 13)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agora.coordinator.pipeline_models import PipelinePhase
from agora.coordinator.pipeline_models import PipelineRetryPolicy
from agora.coordinator.pipeline_errors import PipelineError

logger = logging.getLogger(__name__)


def is_retryable(phase: PipelinePhase) -> bool:
    """Check if a failed phase is retryable per default policy."""
    return phase.value in PipelineRetryPolicy().retryable_phases


async def retry_with_backoff(
    coro_factory: Any, phase: PipelinePhase,
    policy: PipelineRetryPolicy | None = None,
) -> Any:
    """Retry a coroutine with exponential backoff.

    Args:
        coro_factory: Zero-arg async callable returning the coroutine.
        phase: The pipeline phase (used to check retryability).
        policy: Retry policy; defaults to PipelineRetryPolicy().

    Returns:
        Result of the successful coroutine call.

    Raises:
        PipelineError: If phase not retryable or retries exhausted.
    """
    if policy is None:
        policy = PipelineRetryPolicy()

    if not is_retryable(phase):
        raise PipelineError(phase, "Non-retryable failure", retryable=False)

    last_exc: Exception = RuntimeError("unknown")
    for attempt in range(1, policy.max_retries + 1):
        try:
            return await coro_factory()
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Retry %d/%d for phase %s: %s",
                attempt, policy.max_retries, phase.value, exc,
            )
            if attempt < policy.max_retries:
                delay = policy.retry_delay * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

    raise PipelineError(
        phase,
        f"Exhausted {policy.max_retries} retries: {last_exc}",
        retryable=True,
    )
