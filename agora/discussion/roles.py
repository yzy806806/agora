"""Role definitions for Agora discussions.

In v2.0, role identity comes from each worker's SOUL.md (their full Hermes
profile identity). This file provides:

  - CONSENSUS_CHECKER_PROMPT: for the chair's consensus evaluation
  - DISCUSSION_TEMPLATES: pre-configured motion setups for common scenarios

The old ROLE_PROMPTS dict is no longer needed — agents bring their own
identity via their SOUL.md when spawned with `hermes -p <profile> chat -q`.
"""
from __future__ import annotations


CONSENSUS_CHECKER_PROMPT = """\
You are a consensus checker. Analyze the following discussion and determine \
if the participants have reached consensus. Respond with JSON only:

{
  "consensus": true,
  "confidence": 0.0,
  "reason": "<brief explanation>"
}

"consensus" is true only if the participants broadly agree on the direction. \
"confidence" is 0.0-1.0 reflecting how strong the agreement is.
"""


# --------------------------------------------------------------------------- #
#  Discussion templates — pre-configured motion setups for common scenarios   #
# --------------------------------------------------------------------------- #

DISCUSSION_TEMPLATES: dict[str, dict] = {
    "tech_choice": {
        "description": "Technology selection — compare options and make a recommendation",
        "participants": ["architect", "developer", "reviewer"],
        "rounds": 3,
        "prompt_suffix": (
            "Focus on: (1) trade-offs between options, (2) ecosystem maturity "
            "and community support, (3) migration path and lock-in risk, "
            "(4) total cost of ownership."
        ),
    },
    "bug_analysis": {
        "description": "Bug analysis — root cause investigation and fix strategy",
        "participants": ["developer", "reviewer", "tester"],
        "rounds": 2,
        "prompt_suffix": (
            "Focus on: (1) root cause hypotheses, (2) reproduction steps, "
            "(3) fix approach and risk of regression, (4) test coverage needed."
        ),
    },
    "architecture_review": {
        "description": "Architecture review — evaluate a design proposal",
        "participants": ["architect", "developer", "reviewer"],
        "rounds": 3,
        "prompt_suffix": (
            "Focus on: (1) does the design meet the requirements, (2) scalability "
            "and maintainability concerns, (3) what's missing or over-engineered, "
            "(4) concrete improvement suggestions."
        ),
    },
    "security_audit": {
        "description": "Security audit — identify vulnerabilities and mitigation plan",
        "participants": ["reviewer", "architect"],
        "rounds": 3,
        "prompt_suffix": (
            "Focus on: (1) attack surface mapping, (2) authentication/authorization "
            "gaps, (3) data exposure risks, (4) prioritized remediation plan."
        ),
    },
    "research_review": {
        "description": "Research review — evaluate findings and decide direction",
        "participants": ["researcher", "architect", "developer"],
        "rounds": 3,
        "prompt_suffix": (
            "Focus on: (1) credibility and recency of sources, (2) relevance to "
            "the project goal, (3) gaps in the research, (4) concrete next steps."
        ),
    },
    "content_strategy": {
        "description": "Content strategy — plan structure, tone, and audience approach",
        "participants": ["writer", "researcher", "reviewer"],
        "rounds": 3,
        "prompt_suffix": (
            "Focus on: (1) target audience analysis, (2) content structure and "
            "flow, (3) tone and style guidelines, (4) accuracy and sourcing requirements."
        ),
    },
}
