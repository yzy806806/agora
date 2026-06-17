"""CapabilityMatcherV2 — proficiency-weighted agent selection.

Phase 14+.E.4: Matches task requirements against agent skill
declarations, weighting by proficiency level (1-5 scale).

Score = sum(required_skill_weight * agent_proficiency) / total_weight

Falls back to v1 string matching when no v2 capabilities declared.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .capability import capability_match_score as v1_match_score
from .capability_v2 import AgentCapabilities, TaskExecutionCapabilities
from .capability_v2_base import SkillDeclaration, SkillProficiency

logger = logging.getLogger(__name__)

# Default weight for a required skill when not explicitly weighted.
DEFAULT_SKILL_WEIGHT: float = 1.0


@dataclass
class SkillRequirement:
    """A task's requirement for a specific skill."""

    name: str
    weight: float = DEFAULT_SKILL_WEIGHT
    min_proficiency: int = 1  # 1-5, minimum acceptable level


@dataclass
class AgentScore:
    """Score result for a single agent."""

    agent_id: str
    score: float
    matched_skills: list[str] = field(default_factory=list)
    is_v2: bool = True


class CapabilityMatcherV2:
    """Proficiency-weighted capability matcher.

    When an agent declares v2 capabilities (AgentCapabilities with
    SkillDeclarations), scores are weighted by proficiency.
    Falls back to v1 flat-string matching otherwise.
    """

    def match(
        self,
        requirements: list[SkillRequirement],
        agents: list[dict[str, Any]],
    ) -> list[AgentScore]:
        """Score and rank agents against skill requirements.

        Args:
            requirements: Task skill requirements with weights.
            agents: List of agent dicts, each with 'agent_id',
                    'capabilities' (v1 list[str]) and optionally
                    'capabilities_v2' (AgentCapabilities dict).

        Returns:
            Agents sorted by score descending.
        """
        if not requirements:
            return [
                AgentScore(
                    agent_id=a["agent_id"], score=0.5,
                    matched_skills=[], is_v2=False,
                )
                for a in agents
            ]

        scored: list[AgentScore] = []
        for agent in agents:
            result = self._score_agent(requirements, agent)
            if result is not None:
                scored.append(result)

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored

    def _score_agent(
        self,
        requirements: list[SkillRequirement],
        agent: dict[str, Any],
    ) -> Optional[AgentScore]:
        """Score a single agent. Returns None if below min proficiency."""
        v2_caps = agent.get("capabilities_v2")
        aid = agent["agent_id"]

        if v2_caps is not None:
            return self._score_v2(requirements, aid, v2_caps)

        # Fallback to v1
        v1_caps = agent.get("capabilities") or []
        if isinstance(v1_caps, str):
            import json
            v1_caps = json.loads(v1_caps)
        req_names = [r.name for r in requirements]
        score = v1_match_score(v1_caps, req_names)
        if score <= 0:
            return None
        matched = list(set(v1_caps) & set(req_names))
        return AgentScore(
            agent_id=aid, score=score,
            matched_skills=matched, is_v2=False,
        )

    def _score_v2(
        self,
        requirements: list[SkillRequirement],
        agent_id: str,
        v2_caps: Any,
    ) -> Optional[AgentScore]:
        """Score using v2 proficiency-weighted algorithm."""
        if isinstance(v2_caps, dict):
            v2_caps = AgentCapabilities.model_validate(v2_caps)

        skills = v2_caps.task_execution.skills
        skill_map: dict[str, SkillDeclaration] = {
            s.name.lower(): s for s in skills
        }

        total_weight = sum(r.weight for r in requirements)
        if total_weight == 0:
            total_weight = 1.0

        weighted_sum = 0.0
        matched: list[str] = []

        for req in requirements:
            decl = skill_map.get(req.name.lower())
            if decl is None:
                # Skill not declared — zero contribution
                continue
            prof = decl.proficiency_value
            if prof < req.min_proficiency:
                # Below minimum — agent disqualified for this req
                continue
            weighted_sum += req.weight * prof
            matched.append(req.name)

        if not matched:
            return None

        # Normalize: max possible = total_weight * 5 (expert)
        score = weighted_sum / (total_weight * SkillProficiency.EXPERT)
        return AgentScore(
            agent_id=agent_id, score=score,
            matched_skills=matched, is_v2=True,
        )
