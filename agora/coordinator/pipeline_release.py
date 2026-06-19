"""Pipeline release — consolidated from phase + models.

Auto-completes release. Release agent dispatch removed;
real release happens via MCP tools or external CI.
"""
from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ReleaseRequest(BaseModel):
    """Request payload for the releaser agent."""
    pipeline_id: str
    project_id: str
    graph_id: str
    changed_files: list[str] = Field(default_factory=list)
    review_summary: str = ""
    workspace_paths: list[str] = Field(default_factory=list)


class ReleaseResult(BaseModel):
    """Outcome returned by the releaser agent."""
    pipeline_id: str
    outcome: Literal["success", "failed"]
    version: Optional[str] = None
    tag: Optional[str] = None
    error: Optional[str] = None


async def trigger_release(
    hub: Any, graph_result: dict, project_id: str,
    review_summary: str = "", workspace_paths: list[str] | None = None,
) -> str:
    """RELEASING phase: auto-complete (release handled externally)."""
    pipeline_id = graph_result.get("id", "unknown")
    logger.info("Auto-completing release for pipeline %s", pipeline_id)
    return f"release-{pipeline_id}"
