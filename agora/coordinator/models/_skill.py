"""Skill declaration model (migrated from capability_v2_base).

Kept for agent registration metadata; MCP handles capability matching.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ._enums import SkillCategory, SkillProficiency


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
