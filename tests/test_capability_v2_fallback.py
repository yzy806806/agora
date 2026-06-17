"""Tests for CapabilityMatcherV2 — fallback and edge cases.

Phase 14+.E.4
"""
import pytest

from agora.coordinator.capability_v2_base import (
    SkillDeclaration,
    SkillProficiency,
)
from agora.coordinator.capability_v2 import (
    AgentCapabilities,
    TaskExecutionCapabilities,
)
from agora.coordinator.capability_v2_matcher import (
    CapabilityMatcherV2,
    SkillRequirement,
)


def _agent(
    agent_id: str,
    v1_caps: list[str] | None = None,
    v2_skills: list[SkillDeclaration] | None = None,
) -> dict:
    a: dict = {"agent_id": agent_id}
    if v1_caps is not None:
        a["capabilities"] = v1_caps
    if v2_skills is not None:
        a["capabilities_v2"] = AgentCapabilities(
            task_execution=TaskExecutionCapabilities(skills=v2_skills),
        )
    return a


def _skill(name: str, prof: SkillProficiency = SkillProficiency.INTERMEDIATE):
    return SkillDeclaration(name=name, proficiency=prof)


# --- v1 fallback tests ---

def test_fallback_v1_matching():
    """Agents without v2 caps fall back to v1 string matching."""
    matcher = CapabilityMatcherV2()
    reqs = [SkillRequirement(name="code_review")]
    agents = [
        _agent("a", v1_caps=["code_review", "testing"]),
        _agent("b", v1_caps=["documentation"]),
    ]
    results = matcher.match(reqs, agents)
    assert len(results) == 1
    assert results[0].agent_id == "a"
    assert results[0].is_v2 is False


def test_fallback_v1_no_match():
    """v1 agent with no matching caps excluded."""
    matcher = CapabilityMatcherV2()
    reqs = [SkillRequirement(name="devops")]
    agents = [_agent("a", v1_caps=["writing"])]
    results = matcher.match(reqs, agents)
    assert len(results) == 0


def test_fallback_v1_caps_as_json_string():
    """v1 capabilities stored as JSON string."""
    matcher = CapabilityMatcherV2()
    reqs = [SkillRequirement(name="python")]
    agents = [{"agent_id": "a", "capabilities": '["python","go"]'}]
    results = matcher.match(reqs, agents)
    assert len(results) == 1
    assert results[0].agent_id == "a"


def test_mixed_v1_and_v2_agents():
    """Mix of v1 and v2 agents in same match call."""
    matcher = CapabilityMatcherV2()
    reqs = [SkillRequirement(name="python")]
    agents = [
        _agent("v1", v1_caps=["python"]),
        _agent("v2", v2_skills=[_skill("python", SkillProficiency.EXPERT)]),
    ]
    results = matcher.match(reqs, agents)
    # v2 expert should score higher than v1 (which gets 1.0/len=1.0)
    # but v1 score is len(intersection)/len(reqs) = 1.0
    # v2 expert score = 5/(1*5) = 1.0 — equal
    assert len(results) == 2


# --- edge case tests ---

def test_no_requirements():
    """No requirements returns neutral 0.5 for all agents."""
    matcher = CapabilityMatcherV2()
    agents = [
        _agent("a", v2_skills=[_skill("python")]),
        _agent("b", v1_caps=["go"]),
    ]
    results = matcher.match([], agents)
    assert len(results) == 2
    assert all(r.score == 0.5 for r in results)


def test_empty_agents():
    """No agents returns empty list."""
    matcher = CapabilityMatcherV2()
    reqs = [SkillRequirement(name="python")]
    results = matcher.match(reqs, [])
    assert len(results) == 0


def test_v2_caps_as_dict():
    """v2 capabilities passed as plain dict (not AgentCapabilities)."""
    matcher = CapabilityMatcherV2()
    reqs = [SkillRequirement(name="python")]
    agents = [{
        "agent_id": "a",
        "capabilities_v2": {
            "task_execution": {
                "skills": [{"name": "python", "proficiency": 4}],
            },
            "discussion": {"roles": ["participant"], "voting": True},
            "workspace": {"supported_operations": ["read"]},
        },
    }]
    results = matcher.match(reqs, agents)
    assert len(results) == 1
    assert results[0].is_v2 is True


def test_case_insensitive_skill_matching():
    """Skill names matched case-insensitively."""
    matcher = CapabilityMatcherV2()
    reqs = [SkillRequirement(name="Python")]
    agents = [_agent("a", v2_skills=[_skill("python")])]
    results = matcher.match(reqs, agents)
    assert len(results) == 1
    assert "Python" in results[0].matched_skills
