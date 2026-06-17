"""Protocol v2 composite models for agent communication.

Phase 14+.E.1: AgentCapabilities, AgentMetadata, TaskResult,
StructuredError, ProtocolVersion.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from .capability_v2_base import (
    ErrorCategory,
    SkillCategory,
    SkillDeclaration,
    SkillProficiency,
    TaskResultStatus,
)


class DiscussionCapabilities(BaseModel):
    """Structured discussion capabilities."""

    roles: list[str] = Field(default_factory=lambda: ["participant"])
    voting: bool = True


class TaskExecutionCapabilities(BaseModel):
    """Structured task execution capabilities."""

    max_concurrent: int = 2
    skills: list[SkillDeclaration] = Field(default_factory=list)


class WorkspaceCapabilities(BaseModel):
    """Structured workspace capabilities."""

    supported_operations: list[str] = Field(
        default_factory=lambda: ["read", "write"]
    )


class AgentCapabilities(BaseModel):
    """v2 structured capabilities replacing flat string list.

    Maps capability domain to structured configuration.
    """

    discussion: DiscussionCapabilities = Field(
        default_factory=DiscussionCapabilities
    )
    task_execution: TaskExecutionCapabilities = Field(
        default_factory=TaskExecutionCapabilities
    )
    workspace: WorkspaceCapabilities = Field(
        default_factory=WorkspaceCapabilities
    )
