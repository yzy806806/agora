"""Pipeline release models (Phase 13.1d).

ReleaseRequest: sent to releaser agent via TASK_ASSIGNED.
ReleaseResult: returned by releaser after bump/tag/push.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ReleaseRequest(BaseModel):
    """Request payload sent to the releaser agent."""
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
