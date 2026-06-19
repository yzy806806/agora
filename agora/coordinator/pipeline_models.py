"""Pipeline models for the Agora Full-auto Dev Loop (Phase 13)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PipelinePhase(str, Enum):
    """Pipeline lifecycle states."""
    DISCUSSING = "discussing"
    DECOMPOSING = "decomposing"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    RELEASING = "releasing"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineRun(BaseModel):
    """Tracks a single pipeline run from idea to release."""
    id: str
    project_id: str
    idea: str
    motion_id: Optional[str] = None
    graph_id: Optional[str] = None
    phase: PipelinePhase = PipelinePhase.DISCUSSING
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: Optional[datetime] = None
    tasks_total: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    review_outcome: Optional[str] = None  # "approved" | "changes_requested"
    release_version: Optional[str] = None
    error: Optional[str] = None
    workspace_paths: list[str] = Field(default_factory=list)


class PipelineStartRequest(BaseModel):
    """Request body for starting a new pipeline run."""
    idea: str
    project_id: str


class PipelineRetryPolicy(BaseModel):
    """Configurable retry policy for pipeline phases."""
    max_retries: int = 3
    retry_delay: int = 30  # seconds
    retryable_phases: set[str] = {"executing", "reviewing", "releasing"}
    max_task_retries: int = 2
