"""Pipeline release phase (Phase 13.1d).

After review approval, pipeline creates a RELEASE task and sends
TASK_ASSIGNED to the releaser agent via WS. The releaser bumps
version, updates CHANGELOG, creates git tag, and pushes.

On success: pipeline -> COMPLETED, notification sent.
On failure: pipeline -> FAILED, error logged.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from agora.coordinator.pipeline_release_agent import find_release_agent
from agora.coordinator.pipeline_release_models import (
    ReleaseRequest, ReleaseResult,
)
from agora.coordinator.pipeline_errors import ReleaseFailedError

logger = logging.getLogger(__name__)


async def trigger_release(
    hub: Any, graph_result: dict, project_id: str,
    review_summary: str = "", workspace_paths: list[str] | None = None,
) -> str:
    """Phase: RELEASING — trigger the releaser agent.

    Sends TASK_ASSIGNED with RELEASE_REQUEST payload.
    Returns release version string on success.
    Raises ReleaseFailedError on failure.
    """
    try:
        releaser_id = await find_release_agent(hub)
        if not releaser_id:
            raise ReleaseFailedError("No release agent online")
        request = _build_request(
            graph_result, project_id, review_summary, workspace_paths,
        )
        sent = await _dispatch_release(hub, releaser_id, request)
        if not sent:
            raise ReleaseFailedError(f"Cannot reach releaser {releaser_id}")
        logger.info("Release triggered via %s for %s", releaser_id, project_id)
        return f"release-{graph_result.get('id', 'unknown')}"
    except ReleaseFailedError:
        raise
    except Exception as exc:
        raise ReleaseFailedError(str(exc)) from exc


def _build_request(
    graph_result: dict, project_id: str, review_summary: str,
    workspace_paths: list[str] | None = None,
) -> ReleaseRequest:
    """Build a ReleaseRequest from graph result."""
    return ReleaseRequest(
        pipeline_id=graph_result.get("id", ""),
        project_id=project_id,
        graph_id=graph_result.get("id", ""),
        changed_files=graph_result.get("changed_files", []),
        review_summary=review_summary,
        workspace_paths=workspace_paths or [],
    )


async def _dispatch_release(
    hub: Any, releaser_id: str, request: ReleaseRequest,
) -> bool:
    """Send TASK_ASSIGNED with RELEASE_REQUEST payload to releaser."""
    return await hub.send(releaser_id, {
        "type": "TASK_ASSIGNED",
        "payload": {
            "task_type": "RELEASE",
            "request": request.model_dump(),
        },
    })


def process_release_result(result: ReleaseResult) -> str:
    """Process a RELEASE_RESULT from the releaser agent.

    Returns the version string on success.
    Raises ReleaseFailedError on failure.
    """
    if result.outcome == "success":
        logger.info(
            "Release succeeded: version=%s tag=%s",
            result.version, result.tag,
        )
        return result.version or "unknown"
    error = result.error or "Release failed (no error detail)"
    logger.error("Release failed: %s", error)
    raise ReleaseFailedError(error)
