"""Discovery endpoint router (Phase 14+.E.5).

GET /api/v1/discovery — protocol and agent capability discovery.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from .config import settings
from .discovery_models import DiscoveredAgent
from .discovery_response import DiscoveryResponse
from .capability_v2_base import SkillCategory, SkillProficiency
from .capability_v2 import AgentCapabilities
from .storage import Storage
from .ws import manager

logger = logging.getLogger(__name__)

router = APIRouter()

_storage: Optional[Storage] = None


def init_discovery_deps(storage: Storage) -> None:
    """Initialize discovery router dependencies."""
    global _storage
    _storage = storage


def _get_storage() -> Storage:
    if _storage is None:
        raise HTTPException(status_code=503, detail="Not initialized")
    return _storage


def _agent_status(agent: dict) -> str:
    """Derive agent status string from agent record."""
    if not agent.get("is_approved", False):
        return agent.get("approval_status", "pending")
    if agent.get("is_online", False):
        if agent.get("load", 0) >= 0.9:
            return "busy"
        return "online"
    return "offline"


def _build_discovered_agent(agent: dict) -> DiscoveredAgent:
    """Build DiscoveredAgent from storage record."""
    caps_data = agent.get("capabilities_v2")
    if isinstance(caps_data, dict):
        capabilities = AgentCapabilities(**caps_data)
    else:
        capabilities = AgentCapabilities()
    skills = [
        s.model_dump() for s in capabilities.task_execution.skills
    ]
    return DiscoveredAgent(
        agent_id=agent["agent_id"],
        name=agent.get("name", ""),
        model=agent.get("model", ""),
        status=_agent_status(agent),
        capabilities=capabilities,
        skills=skills,
    )


@router.get("/discovery", response_model=DiscoveryResponse)
async def discovery(
    skill_category: Optional[str] = None,
    min_proficiency: Optional[int] = None,
    status: Optional[str] = None,
) -> DiscoveryResponse:
    """Protocol and agent capability discovery endpoint."""
    storage = _get_storage()
    agents_raw = await storage.list_agents()
    discovered = [_build_discovered_agent(a) for a in agents_raw]
    # Filter by skill category
    if skill_category is not None:
        try:
            cat = SkillCategory(skill_category)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid skill_category: {skill_category}",
            )
        discovered = [
            a for a in discovered
            if any(s.get("category") == cat.value for s in a.skills)
        ]
    # Filter by minimum proficiency
    if min_proficiency is not None:
        if min_proficiency < 1 or min_proficiency > 5:
            raise HTTPException(
                status_code=400,
                detail="min_proficiency must be 1-5",
            )
        discovered = [
            a for a in discovered
            if any(
                s.get("proficiency", 1) >= min_proficiency
                for s in a.skills
            )
        ]
    # Filter by status
    if status is not None:
        discovered = [
            a for a in discovered if a.status == status
        ]
    return DiscoveryResponse(
        server_version=getattr(settings, "version", ""),
        agents=discovered,
    )
