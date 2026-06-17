"""Pydantic response models for dashboard API endpoints (Phase 11.1a)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from .task_models import ExecutionSlot, TaskNode, TaskStatus


class TaskItem(BaseModel):
    """Lightweight task item for list responses."""

    id: str
    graph_id: str
    motion_id: str
    title: str
    status: TaskStatus
    assigned_to: Optional[str] = None
    depends_on: list[str] = Field(default_factory=list)
    retry_count: int = 0
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TaskListResponse(BaseModel):
    """Paginated task list response."""

    tasks: list[TaskItem]
    total: int
    limit: int
    offset: int


class TaskDetailResponse(BaseModel):
    """Full task detail with subtask (dependency) info."""

    id: str
    graph_id: str
    motion_id: str
    title: str
    description: str = ""
    status: TaskStatus
    assigned_to: Optional[str] = None
    required_capabilities: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TaskGraphItem(BaseModel):
    """Lightweight graph item for list responses."""

    id: str
    motion_id: str
    parallel_mode: str = "auto"
    max_parallel_slots: int = 10
    created_at: Optional[datetime] = None


class TaskGraphDetailResponse(BaseModel):
    """Graph with all tasks included."""

    id: str
    motion_id: str
    parallel_mode: str = "auto"
    max_parallel_slots: int = 10
    resource_conflict_policy: str = "warn"
    created_at: Optional[datetime] = None
    tasks: list[TaskDetailResponse] = Field(default_factory=list)


class TaskGraphListResponse(BaseModel):
    """Paginated task graph list response."""

    graphs: list[TaskGraphItem]
    total: int
    limit: int
    offset: int


class ExecutionSlotItem(BaseModel):
    """Single execution slot for dashboard display."""

    task_id: str
    agent_id: str
    started_at: Optional[datetime] = None
    status: str = "running"


class ExecutionSlotsResponse(BaseModel):
    """Current execution slot status."""

    slots: list[ExecutionSlotItem]
    total: int


# --- Audit query models (Phase 11.1d) ---


class AuditEventItem(BaseModel):
    """Single audit event in query response."""

    id: int
    event_type: str
    actor_id: str
    actor_role: str = ""
    action: str
    resource: str = ""
    details: dict = {}
    timestamp: str
    tenant_id: str = "default"


class AuditQueryResponse(BaseModel):
    """Paginated audit log query response."""

    events: list[AuditEventItem]
    total: int
    limit: int
    offset: int


# --- Task result response model (Phase 14+.E.3) ---

class TaskResultResponse(BaseModel):
    """Structured task result from Protocol v2."""
    task_id: str
    status: str
    output: dict[str, Any] = Field(default_factory=dict)
    error: Optional[dict[str, Any]] = None
    metrics: Optional[dict[str, Any]] = None
