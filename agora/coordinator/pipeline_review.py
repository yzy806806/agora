"""Pipeline code review — consolidated from review/reviewer/handler/phase modules.

Auto-approves reviews. Review agent dispatch removed;
real review happens via MCP tools or external agents.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field
from typing import Literal, Optional

logger = logging.getLogger(__name__)


# ---- Models ----

class ReviewIssue(BaseModel):
    """A single issue found during code review."""
    file: str
    line: Optional[int] = None
    severity: Literal["critical", "major", "minor"]
    description: str


class ReviewRequest(BaseModel):
    """Request to review code changes from a pipeline run."""
    pipeline_id: str
    changed_files: list[str] = Field(default_factory=list)
    task_results: list[dict] = Field(default_factory=list)
    test_results: dict = Field(default_factory=dict)


class ReviewResult(BaseModel):
    """Outcome of a code review for a pipeline run."""
    pipeline_id: str
    reviewer_id: str
    outcome: Literal["approved", "changes_requested"]
    issues: list[ReviewIssue] = Field(default_factory=list)
    summary: str = ""


# ---- Auto-approve phase ----

async def trigger_code_review(
    hub: Any, graph_result: dict, project_id: str,
    storage: Any = None,
) -> ReviewResult:
    """REVIEWING phase: auto-approve (review handled externally)."""
    pipeline_id = graph_result.get("id", "")
    logger.info("Auto-approving review for pipeline %s", pipeline_id)
    return ReviewResult(
        pipeline_id=pipeline_id,
        reviewer_id="auto",
        outcome="approved",
        issues=[],
        summary="Auto-approved (review_agent removed)",
    )


async def collect_changed_files(
    storage: Any, graph_id: str,
) -> list[str]:
    """Collect artifact_paths from all completed tasks in a graph."""
    tasks = await storage.list_tasks(graph_id=graph_id, status="done")
    files: list[str] = []
    for t in tasks:
        for p in t.get("artifact_paths", []):
            if p and p not in files:
                files.append(p)
    return files


async def dispatch_review_request(
    hub: Any, reviewer_id: str, request: ReviewRequest,
) -> bool:
    """Send REVIEW_REQUEST to the reviewer agent."""
    sent = await hub.send(reviewer_id, {
        "type": "REVIEW_REQUEST",
        "payload": request.model_dump(),
    })
    if sent:
        logger.info("Review dispatched to %s for pipeline %s",
                     reviewer_id, request.pipeline_id)
    else:
        logger.warning("Failed to dispatch review to %s", reviewer_id)
    return sent


# ---- Handler helpers ----

def parse_review_result(payload: dict) -> ReviewResult:
    """Parse a REVIEW_RESULT payload into ReviewResult."""
    issues = []
    for raw in payload.get("issues", []):
        issues.append(ReviewIssue(
            file=raw["file"],
            line=raw.get("line"),
            severity=raw["severity"],
            description=raw["description"],
        ))
    return ReviewResult(
        pipeline_id=payload["pipeline_id"],
        reviewer_id=payload["reviewer_id"],
        outcome=payload["outcome"],
        issues=issues,
        summary=payload.get("summary", ""),
    )


async def process_incoming_review_result(
    result: ReviewResult, storage: Any,
) -> list[str]:
    """Process REVIEW_RESULT. Returns fix task IDs if changes requested."""
    if result.outcome == "approved":
        logger.info("Review approved for pipeline %s", result.pipeline_id)
        return []
    return await register_fix_tasks(result, storage)


async def register_fix_tasks(
    result: ReviewResult, storage: Any,
) -> list[str]:
    """Create fix tasks in storage for each review issue."""
    task_ids: list[str] = []
    for issue in result.issues:
        tid = await storage.create_task({
            "type": "fix", "file": issue.file,
            "line": issue.line, "severity": issue.severity,
            "description": issue.description,
            "reviewer_id": result.reviewer_id,
            "pipeline_id": result.pipeline_id, "status": "pending",
        })
        task_ids.append(tid)
    return task_ids


def build_fix_tasks(result: ReviewResult) -> list[dict]:
    """Create fix task dicts from a changes_requested result."""
    return [
        {"type": "fix", "file": i.file, "line": i.line,
         "severity": i.severity, "description": i.description,
         "reviewer_id": result.reviewer_id}
        for i in result.issues
    ]


# ---- PipelineReviewer (backward compat) ----

def process_review_response(result: ReviewResult) -> list[dict]:
    """Process a REVIEW_RESULT, returning fix tasks if changes requested."""
    if result.outcome == "approved":
        return []
    return build_fix_tasks(result)


class PipelineReviewer:
    """Orchestrates code review (simplified, auto-approve)."""

    def __init__(self, hub: Any) -> None:
        self.hub = hub

    async def request_review(
        self, pipeline_id: str, changed_files: list[str],
    ) -> ReviewResult:
        return ReviewResult(
            pipeline_id=pipeline_id, reviewer_id="auto",
            outcome="approved", issues=[], summary="Auto-approved",
        )

    async def process_review_result(self, result: ReviewResult) -> list[dict]:
        if result.outcome == "approved":
            return []
        return build_fix_tasks(result)

    async def re_review(
        self, pipeline_id: str, fix_tasks: list[dict],
    ) -> ReviewResult:
        return ReviewResult(
            pipeline_id=pipeline_id, reviewer_id="auto",
            outcome="approved", issues=[], summary="Auto-approved",
        )
