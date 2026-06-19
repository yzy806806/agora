"""AgoraAgentClient — main SDK client for connecting agents to Agora.

Phase 16.10: WS-based methods removed (speak, vote, task reporting).
Agents now communicate via MCP tools. This client provides HTTP
registration and task management only.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import AgentConnectionConfig
from .protocol import AgentConfig, RegistrationResult

logger = logging.getLogger(__name__)


class AgoraAgentClient:
    """SDK client for an agent to connect to Agora Coordinator."""

    def __init__(self, config: AgentConnectionConfig) -> None:
        self._config = config
        self._http = httpx.AsyncClient(
            base_url=config.coordinator_url, timeout=30.0
        )
        self._agent_config: AgentConfig | None = None

    @property
    def config(self) -> AgentConnectionConfig:
        return self._config

    @property
    def agent_config(self) -> AgentConfig | None:
        return self._agent_config

    async def register(self) -> RegistrationResult:
        """Register this agent with the Coordinator (HTTP POST)."""
        body = {
            "agent_id": self._config.agent_id,
            "name": self._config.agent_name,
            "agent_type": self._config.agent_type,
            "capabilities": self._config.capabilities,
            "model": self._config.model,
        }
        resp = await self._http.post(
            "/api/v1/agents/register", json=body
        )
        resp.raise_for_status()
        data = resp.json()
        self._config.agent_token = data.get("agent_token", "")
        return RegistrationResult(**data)

    async def create_motion(self, title: str, desc: str = "") -> dict:
        """Create a new discussion motion via HTTP."""
        resp = await self._http.post(
            "/api/v1/motions",
            json={"title": title, "description": desc},
        )
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()
