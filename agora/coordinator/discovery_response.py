"""Discovery response model (Phase 14+.E.5).

Split from discovery_models.py to keep each file under 80 lines.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .discovery_models import (
    DiscoveryAuth,
    DiscoveryFeatures,
    DiscoveryRateLimits,
    DiscoveredAgent,
)


class DiscoveryResponse(BaseModel):
    """Response for GET /api/v1/discovery."""

    protocol_versions: list[str] = Field(
        default_factory=lambda: ["1.0", "2.0"]
    )
    server_version: str = ""
    features: DiscoveryFeatures = Field(
        default_factory=DiscoveryFeatures
    )
    rate_limits: DiscoveryRateLimits = Field(
        default_factory=DiscoveryRateLimits
    )
    auth: DiscoveryAuth = Field(default_factory=DiscoveryAuth)
    api_version: str = "v1"
    agents: list[DiscoveredAgent] = Field(default_factory=list)
