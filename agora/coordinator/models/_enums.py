"""Enums migrated from capability_v2_base.

MCP replaces capability v2 matching, but these enums
are still used by task result and skill models.
"""
from __future__ import annotations

from enum import Enum


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
