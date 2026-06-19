"""Discovery endpoint router (Phase 14+.E.5).

GET /api/v1/discovery — protocol and agent capability discovery.
Simplified: removed capability_v2 dependency, uses flat capabilities list.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from .config import settings
from .discovery_models import DiscoveredAgent
from .discovery_response import DiscoveryResponse
from .storage import Storage

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
    caps_raw = agent.get("capabilities") or []
    if isinstance(caps_raw, str):
        try:
            caps_raw = json.loads(caps_raw)
        except (json.JSONDecodeError, TypeError):
            caps_raw = []
    return DiscoveredAgent(
        agent_id=agent["agent_id"],
        name=agent.get("name", ""),
        model=agent.get("model", ""),
        status=_agent_status(agent),
        capabilities=caps_raw if isinstance(caps_raw, list) else [],
        skills=[],
    )


@router.get("/discovery", response_model=DiscoveryResponse)
async def discovery(
    status: Optional[str] = None,
) -> DiscoveryResponse:
    """Protocol and agent capability discovery endpoint."""
    storage = _get_storage()
    agents_raw = await storage.list_agents()
    discovered = [_build_discovered_agent(a) for a in agents_raw]
    # Filter by status
    if status is not None:
        discovered = [
            a for a in discovered if a.status == status
        ]
    return DiscoveryResponse(
        server_version=getattr(settings, "version", ""),
        agents=discovered,
    )
