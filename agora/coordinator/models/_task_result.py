"""Task result models (migrated from capability_v2_messages).

Used by task_exec.py for structured task result handling.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from ._enums import ErrorCategory, TaskResultStatus


class StructuredError(BaseModel):
    """Structured error with code, category, and optional diagnostics."""

    code: str
    category: ErrorCategory = ErrorCategory.INTERNAL
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    stack_trace: Optional[str] = None
    retry_hint: Optional[str] = None


class TaskMetrics(BaseModel):
    """Optional resource usage metrics for a task result."""

    wall_time_seconds: Optional[float] = None
    tokens_used: Optional[int] = None
    peak_memory_mb: Optional[float] = None


class TaskOutput(BaseModel):
    """Structured task output with artifacts and counts."""

    changed_files: list[str] = Field(default_factory=list)
    tests_run: Optional[int] = None
    tests_passed: Optional[int] = None
    artifacts: list[str] = Field(default_factory=list)


class TaskResult(BaseModel):
    """Structured task result replacing flat success/error."""

    task_id: str
    status: TaskResultStatus = TaskResultStatus.SUCCESS
    output: TaskOutput = Field(default_factory=TaskOutput)
    error: Optional[StructuredError] = None
    metrics: Optional[TaskMetrics] = None
