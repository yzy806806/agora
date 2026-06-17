"""Protocol v2 enums and leaf models for agent capabilities.

Phase 14+.E.1: Structured skill declarations with proficiency levels.

NOTE: TaskResult and StructuredError are defined in
capability_v2_messages.py (matching design doc E.3). They are
re-exported here for backward compatibility.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SkillProficiency(int, Enum):
    """Skill proficiency level (1-5 scale)."""

    NOVICE = 1
    BEGINNER = 2
    INTERMEDIATE = 3
    ADVANCED = 4
    EXPERT = 5


class SkillCategory(str, Enum):
    """Broad skill categories for classification."""

    PROGRAMMING = "programming"
    CODE_REVIEW = "code_review"
    TESTING = "testing"
    DEVOPS = "devops"
    RESEARCH = "research"
    WRITING = "writing"
    ANALYSIS = "analysis"
    DESIGN = "design"
    COMMUNICATION = "communication"
    CUSTOM = "custom"


class TaskResultStatus(str, Enum):
    """Task result status values."""

    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class ErrorCategory(str, Enum):
    """Structured error categories."""

    VALIDATION = "validation"
    EXECUTION = "execution"
    TIMEOUT = "timeout"
    RESOURCE = "resource"
    DEPENDENCY = "dependency"
    INTERNAL = "internal"
    EXTERNAL = "external"


class SkillDeclaration(BaseModel):
    """A structured skill declaration with proficiency level."""

    name: str
    category: SkillCategory = SkillCategory.CUSTOM
    proficiency: SkillProficiency = SkillProficiency.INTERMEDIATE
    description: str = ""
    certifications: list[str] = Field(default_factory=list)

    @property
    def proficiency_value(self) -> int:
        """Numeric proficiency for scoring."""
        return self.proficiency.value


# Re-export canonical TaskResult / StructuredError from
# capability_v2_messages for backward compatibility.
# Use lazy import to avoid circular dependencies.
def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name in ("TaskResult", "StructuredError"):
        from .capability_v2_messages import TaskResult, StructuredError
        return locals().setdefault(name, TaskResult if name == "TaskResult" else StructuredError)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
