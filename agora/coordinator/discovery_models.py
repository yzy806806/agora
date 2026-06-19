"""Discovery endpoint response models (Phase 14+.E.5).

Models for GET /api/v1/discovery — protocol and capability discovery.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class DiscoveryFeatures(BaseModel):
    """Server feature capabilities advertised via discovery."""

    discussion: dict[str, Any] = Field(
        default_factory=lambda: {
            "voting_methods": [
                "simple_majority", "weighted", "ranked_choice"
            ]
        }
    )
    task_execution: dict[str, Any] = Field(
        default_factory=lambda: {
            "dependencies": True, "parallel": True
        }
    )
    workspace: dict[str, Any] = Field(
        default_factory=lambda: {"backends": ["local", "s3"]}
    )
    webhooks: dict[str, Any] = Field(
        default_factory=lambda: {"enabled": True}
    )


class DiscoveryRateLimits(BaseModel):
    """Server rate limit information."""

    default_tpm: int = 10000
    max_concurrent_tasks: int = 10


class DiscoveryAuth(BaseModel):
    """Authentication methods and endpoints."""

    methods: list[str] = Field(
        default_factory=lambda: ["token", "hmac"]
    )
    token_endpoint: str = "/api/v1/auth/token"


class DiscoveredAgent(BaseModel):
    """An agent listed in discovery results."""

    agent_id: str
    name: str
    model: str = ""
    status: str = "offline"
    capabilities: list[str] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)
