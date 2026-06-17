"""Tests for CapabilityMatcherV2 — proficiency-weighted matching.

Phase 14+.E.4
"""
import pytest

from agora.coordinator.capability_v2_base import (
    SkillCategory,
    SkillDeclaration,
    SkillProficiency,
)
from agora.coordinator.capability_v2 import (
    AgentCapabilities,
    TaskExecutionCapabilities,
)
from agora.coordinator.capability_v2_matcher import (
    AgentScore,
    CapabilityMatcherV2,
    SkillRequirement,
)


def _agent(
    agent_id: str,
    v1_caps: list[str] | None = None,
    v2_skills: list[SkillDeclaration] | None = None,
) -> dict:
    """Build an agent dict for testing."""
    a: dict = {"agent_id": agent_id}
    if v1_caps is not None:
        a["capabilities"] = v1_caps
    if v2_skills is not None:
        a["capabilities_v2"] = AgentCapabilities(
            task_execution=TaskExecutionCapabilities(skills=v2_skills),
        )
    return a


def _skill(
    name: str,
    prof: SkillProficiency = SkillProficiency.INTERMEDIATE,
    cat: SkillCategory = SkillCategory.CUSTOM,
) -> SkillDeclaration:
    return SkillDeclaration(name=name, proficiency=prof, category=cat)


# --- v2 scoring tests ---

def test_v2_expert_beats_novice():
    """Expert in a skill should score higher than novice."""
    matcher = CapabilityMatcherV2()
    reqs = [SkillRequirement(name="python", weight=1.0)]
    agents = [
        _agent("novice", v2_skills=[_skill("python", SkillProficiency.NOVICE)]),
        _agent("expert", v2_skills=[_skill("python", SkillProficiency.EXPERT)]),
    ]
    results = matcher.match(reqs, agents)
    assert results[0].agent_id == "expert"
    assert results[0].score > results[1].score


def test_v2_weighted_requirements():
    """Critical skills (higher weight) should dominate score."""
    matcher = CapabilityMatcherV2()
    reqs = [
        SkillRequirement(name="python", weight=3.0),
        SkillRequirement(name="documentation", weight=1.0),
    ]
    # Agent A: expert python, novice docs
    a = _agent("a", v2_skills=[
        _skill("python", SkillProficiency.EXPERT),
        _skill("documentation", SkillProficiency.NOVICE),
    ])
    # Agent B: novice python, expert docs
    b = _agent("b", v2_skills=[
        _skill("python", SkillProficiency.NOVICE),
        _skill("documentation", SkillProficiency.EXPERT),
    ])
    results = matcher.match(reqs, [a, b])
    # A should win because python has 3x weight
    assert results[0].agent_id == "a"


def test_v2_min_proficiency_filter():
    """Agent below min_proficiency is excluded."""
    matcher = CapabilityMatcherV2()
    reqs = [SkillRequirement(name="rust", min_proficiency=4)]
    agents = [
        _agent("low", v2_skills=[_skill("rust", SkillProficiency.BEGINNER)]),
        _agent("high", v2_skills=[_skill("rust", SkillProficiency.EXPERT)]),
    ]
    results = matcher.match(reqs, agents)
    assert len(results) == 1
    assert results[0].agent_id == "high"


def test_v2_no_matching_skills():
    """Agent with no matching skills returns empty."""
    matcher = CapabilityMatcherV2()
    reqs = [SkillRequirement(name="java")]
    agents = [_agent("a", v2_skills=[_skill("python")])]
    results = matcher.match(reqs, agents)
    assert len(results) == 0


def test_v2_equal_proficiency():
    """Equal proficiency yields equal scores."""
    matcher = CapabilityMatcherV2()
    reqs = [SkillRequirement(name="go")]
    agents = [
        _agent("a", v2_skills=[_skill("go", SkillProficiency.ADVANCED)]),
        _agent("b", v2_skills=[_skill("go", SkillProficiency.ADVANCED)]),
    ]
    results = matcher.match(reqs, agents)
    assert len(results) == 2
    assert results[0].score == results[1].score


def test_v2_score_normalization():
    """Score is normalized to 0-1 range (expert=1.0)."""
    matcher = CapabilityMatcherV2()
    reqs = [SkillRequirement(name="python", weight=1.0)]
    agents = [
        _agent("expert", v2_skills=[
            _skill("python", SkillProficiency.EXPERT),
        ]),
    ]
    results = matcher.match(reqs, agents)
    assert len(results) == 1
    assert results[0].score == 1.0


def test_v2_partial_match():
    """Agent matching some but not all requirements."""
    matcher = CapabilityMatcherV2()
    reqs = [
        SkillRequirement(name="python", weight=1.0),
        SkillRequirement(name="rust", weight=1.0),
    ]
    agents = [
        _agent("a", v2_skills=[_skill("python", SkillProficiency.EXPERT)]),
    ]
    results = matcher.match(reqs, agents)
    assert len(results) == 1
    # python=5, rust=0, total_weight=2, max=2*5=10
    # score = 5/10 = 0.5
    assert results[0].score == pytest.approx(0.5)
