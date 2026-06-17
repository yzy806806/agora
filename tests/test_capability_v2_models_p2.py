"""Tests for Protocol v2 composite models (Phase 14+.E.1) — part 2.

Covers: AgentCapabilities, StructuredError, TaskResult,
AgentMetadata, ProtocolVersion, re-exports.
"""
import pytest

from agora.coordinator.capability_v2_base import (
    ErrorCategory,
    SkillCategory,
    SkillDeclaration,
    SkillProficiency,
    TaskResultStatus,
)
from agora.coordinator.capability_v2 import AgentCapabilities
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


# --- AgentCapabilities ---

def test_agent_capabilities_defaults():
    caps = AgentCapabilities()
    assert caps.discussion.voting is True
    assert caps.task_execution.max_concurrent == 2
    assert caps.workspace.supported_operations == ["read", "write"]


def test_agent_capabilities_with_skills():
    skill = SkillDeclaration(
        name="python", proficiency=SkillProficiency.EXPERT,
    )
    caps = AgentCapabilities(
        task_execution={"max_concurrent": 4, "skills": [skill]},
    )
    assert len(caps.task_execution.skills) == 1
    assert caps.task_execution.skills[0].name == "python"


# --- StructuredError ---

def test_structured_error_minimal():
    err = StructuredError(code="ERR001", message="boom")
    assert err.category == ErrorCategory.INTERNAL
    assert err.details == {}
    assert err.stack_trace is None
    assert err.retry_hint is None


def test_structured_error_full():
    err = StructuredError(
        code="TEST_FAILURE",
        category=ErrorCategory.EXECUTION,
        message="2 tests failed",
        details={"failed_tests": ["test_a", "test_b"]},
        stack_trace="AssertionError: ...",
        retry_hint="review_test_logic",
    )
    assert err.category == ErrorCategory.EXECUTION
    assert err.retry_hint == "review_test_logic"


# --- TaskResult ---

def test_task_result_success():
    tr = TaskResult(task_id="t-1")
    assert tr.status == TaskResultStatus.SUCCESS
    assert tr.error is None
    assert tr.metrics is None


def test_task_result_failed():
    err = StructuredError(code="FAIL", message="bad")
    tr = TaskResult(
        task_id="t-2",
        status=TaskResultStatus.FAILED,
        error=err,
        metrics=TaskMetrics(wall_time_seconds=45.2, tokens_used=1500),
    )
    assert tr.status == TaskResultStatus.FAILED
    assert tr.error.code == "FAIL"
    assert tr.metrics.tokens_used == 1500


def test_task_result_partial():
    tr = TaskResult(
        task_id="t-3",
        status=TaskResultStatus.PARTIAL,
        output=TaskOutput(
            changed_files=["a.py"],
            tests_run=10,
            tests_passed=8,
        ),
    )
    assert tr.output.tests_run == 10
    assert tr.output.tests_passed == 8
