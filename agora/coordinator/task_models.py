"""Task models for the Agora Task Execution Engine."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Task lifecycle states."""
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    DONE = "done"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"


class TaskPriority(str, Enum):
    """Task priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TaskNode(BaseModel):
    """A single task node in the task graph."""
    id: str
    graph_id: str
    motion_id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    assigned_to: Optional[str] = None
    required_capabilities: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    workspace_paths: list[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    retry_count: int = 0  # Phase 10.1e: how many times retried
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TaskGraph(BaseModel):
    """DAG of tasks generated from a discussion."""
    id: str
    motion_id: str
    tasks: list[TaskNode] = Field(default_factory=list)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    # Phase 10: parallel execution metadata
    parallel_mode: str = "auto"  # auto | sequential | parallel
    max_parallel_slots: int = 10  # global cap
    resource_conflict_policy: str = "warn"  # warn | abort | queue
    abort_on_failure: bool = False  # Phase 10.1e: cancel graph on any failure


class ExecutionSlot(BaseModel):
    """Tracks one concurrent execution slot (Phase 10)."""
    task_id: str
    agent_id: str
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    status: str = "running"  # running | completing


class ConflictReport(BaseModel):
    """Reports a resource conflict between two tasks (Phase 10)."""
    task_a: str
    task_b: str
    resource_path: str
    conflict_type: str = "write-write"  # write-write | read-write


class ResourceLock(BaseModel):
    """Tracks resource conflicts between parallel tasks (Phase 10)."""
    resource_path: str  # e.g. "src/module.py"
    locked_by: str  # task_id holding the lock
    waiting_tasks: list[str] = Field(default_factory=list)
    lock_type: str = "write"  # write | read
    acquired_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
