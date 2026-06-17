"""Tests for Protocol v2 message models (Phase 14+.E.1).

Covers: SkillDeclaration, SkillProficiency, SkillCategory,
AgentCapabilities, StructuredError, TaskResult, AgentMetadata,
ProtocolVersion, and models/__init__.py re-exports.
"""
import pytest

from agora.coordinator.capability_v2_base import (
    ErrorCategory,
    SkillCategory,
    SkillDeclaration,
    SkillProficiency,
    TaskResultStatus,
)
from agora.coordinator.capability_v2 import (
    AgentCapabilities,
    DiscussionCapabilities,
    TaskExecutionCapabilities,
    WorkspaceCapabilities,
)
from agora.coordinator.capability_v2_messages import (
    StructuredError,
    TaskMetrics,
    TaskOutput,
    TaskResult,
)
from agora.coordinator.capability_v2_meta import (
    AgentMetadata,
    ProtocolVersion,
)


# --- SkillDeclaration & enums ---

def test_skill_proficiency_values():
    assert SkillProficiency.NOVICE == 1
    assert SkillProficiency.EXPERT == 5
    assert SkillProficiency.INTERMEDIATE == 3


def test_skill_declaration_defaults():
    sd = SkillDeclaration(name="python")
    assert sd.category == SkillCategory.CUSTOM
    assert sd.proficiency == SkillProficiency.INTERMEDIATE
    assert sd.description == ""
    assert sd.certifications == []
    assert sd.proficiency_value == 3


def test_skill_declaration_full():
    sd = SkillDeclaration(
        name="code-review",
        category=SkillCategory.CODE_REVIEW,
        proficiency=SkillProficiency.EXPERT,
        description="Expert PR reviewer",
        certifications=["cert-1"],
    )
    assert sd.proficiency_value == 5
    assert sd.category == SkillCategory.CODE_REVIEW


def test_skill_category_values():
    assert SkillCategory.PROGRAMMING == "programming"
    assert SkillCategory.DEVOPS == "devops"
