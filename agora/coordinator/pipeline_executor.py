"""Pipeline phase executor — runs all phases in sequence (Phase 13).

Phase 13.1c: On CHANGES_REQUESTED from review, creates fix tasks
and re-enters EXECUTING phase (up to max_review_rounds).
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from agora.coordinator.pipeline_models import PipelinePhase, PipelineRun
from agora.coordinator.pipeline_retry import is_retryable, retry_with_backoff
from agora.coordinator.pipeline_phase_discuss import (
    create_and_run_discussion, generate_task_graph,
)
from agora.coordinator.pipeline_phase_review import (
    trigger_code_review, process_review_response,
)
from agora.coordinator.pipeline_phase_release import trigger_release
from agora.coordinator.pipeline_phase_record import record_pipeline_session
from agora.coordinator.pipeline_workspace import (
    ensure_project_root, augment_graph_with_paths,
)
from agora.coordinator.pipeline_workspace_review import (
    collect_workspace_changed_files,
)

if TYPE_CHECKING:
    from agora.coordinator.pipeline import PipelineOrchestrator

logger = logging.getLogger(__name__)

DEFAULT_MAX_REVIEW_ROUNDS = 3


def _set_workspace_paths(graph: dict) -> None:
    """Set workspace_paths on each task from graph-level mapping.

    augment_graph_with_paths stores workspace_paths as a dict
    mapping task_id → list[str] on the graph.  This function
    propagates those paths into each TaskNode.workspace_paths
    so they travel with the task through assignment + execution.
    """
    ws_map = graph.get("workspace_paths", {})
    tasks = graph.get("tasks", [])
    for task in tasks:
        paths = ws_map.get(task.id, [])
        if paths:
            task.workspace_paths = paths


async def execute_phases(
    orch: "PipelineOrchestrator", run: PipelineRun,
) -> None:
    """Run through all pipeline phases in order."""
    # Phase 1: Discuss
    run.phase = PipelinePhase.DISCUSSING
    motion_id = await create_and_run_discussion(
        orch.bootstrap, run.idea, run.project_id,
    )
    run.motion_id = motion_id

    # Phase 2: Decompose
    run.phase = PipelinePhase.DECOMPOSING
    graph = await generate_task_graph(orch.bootstrap, motion_id)
    run.graph_id = graph.get("id")
    run.tasks_total = len(graph.get("task_ids", []))
    # Workspace: ensure project root + augment graph with paths
    if orch.workspace_manager:
        await ensure_project_root(orch.workspace_manager, run.project_id)
        graph = augment_graph_with_paths(graph)
        run.workspace_paths = list(
            graph.get("workspace_paths", {}).keys()
        )

    # Phase 3: Execute (parallel where possible)
    run.phase = PipelinePhase.EXECUTING
    results = await _retryable(
        lambda: orch.parallel.execute_graph(graph), run, orch,
    )
    run.tasks_completed = len(results.get("completed", []))
    run.tasks_failed = len(results.get("failed", []))

    # Phase 4: Review (with fix-retry loop)
    run.phase = PipelinePhase.REVIEWING
    # Workspace: collect changed files from workspace for reviewer
    if orch.workspace_manager:
        ws_files = await collect_workspace_changed_files(
            orch.workspace_manager, run.project_id, graph,
        )
        graph["changed_files"] = ws_files
    max_rounds = getattr(orch.retry_policy, "max_retries", DEFAULT_MAX_REVIEW_ROUNDS)
    review = await _review_loop(orch, run, graph, max_rounds)
    run.review_outcome = review.outcome
    if review.outcome != "approved":
        return  # Stop; changes requested and fix rounds exhausted

    # Phase 5: Release
    run.phase = PipelinePhase.RELEASING
    review_summary = getattr(review, "summary", "")
    release_id = await _retryable(
        lambda: trigger_release(
            orch.hub, graph, run.project_id, review_summary,
            run.workspace_paths or None,
        ), run, orch,
    )
    run.release_version = release_id

    # Phase 6: Record session + notify
    await record_pipeline_session(orch.storage, run)
    await _notify_completed(orch, run)


async def _review_loop(
    orch: "PipelineOrchestrator", run: PipelineRun,
    graph: dict, max_rounds: int,
) -> Any:
    """Review -> fix -> re-execute loop with bounded rounds."""
    from agora.coordinator.pipeline_review_models import ReviewResult
    last_review: ReviewResult | None = None
    for round_num in range(1, max_rounds + 1):
        last_review = await _retryable(
            lambda: trigger_code_review(
                orch.hub, graph, run.project_id, orch.storage,
            ), run, orch,
        )
        assert last_review is not None  # guaranteed by _retryable
        if last_review.outcome == "approved":
            return last_review
        fix_tasks = process_review_response(last_review)
        if not fix_tasks:
            return last_review
        logger.info("Review round %d: %d fix tasks", round_num, len(fix_tasks))
        # Re-enter EXECUTING for fix tasks
        run.phase = PipelinePhase.EXECUTING
        fix_result = await orch.parallel.execute_fix_tasks(
            graph, fix_tasks,
        )
        run.tasks_completed += len(fix_result.get("completed", []))
        run.tasks_failed += len(fix_result.get("failed", []))
        run.phase = PipelinePhase.REVIEWING
    # Exhausted rounds — return last review (changes_requested)
    assert last_review is not None
    return last_review


async def _retryable(
    coro_factory: Any, run: PipelineRun,
    orch: "PipelineOrchestrator",
) -> Any:
    """Execute a phase with retry if the phase is retryable."""
    if is_retryable(run.phase):
        return await retry_with_backoff(
            coro_factory, run.phase, orch.retry_policy,
        )
    return await coro_factory()


async def _notify_completed(
    orch: "PipelineOrchestrator", run: PipelineRun,
) -> None:
    """Fire pipeline completion/failed notification if manager is wired."""
    nm = orch.notification_manager
    if nm is None:
        return
    try:
        if run.phase == PipelinePhase.COMPLETED:
            summary = f"{run.tasks_completed}/{run.tasks_total} tasks, v{run.release_version}"
            await nm.notify_pipeline_completed(run.id, run.project_id, summary)
        elif run.phase == PipelinePhase.FAILED:
            await nm.notify_pipeline_failed(run.id, run.project_id, run.error or "unknown")
    except Exception:
        logger.warning("Failed to send pipeline notification", exc_info=True)
