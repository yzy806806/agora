"""Protocol v2 metadata and version negotiation models.

Phase 14+.E.1: AgentMetadata, ProtocolVersion.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentMetadata(BaseModel):
    """Agent self-description metadata (v2)."""

    version: str = ""
    homepage: Optional[str] = None
    description: str = ""
    docs_url: Optional[str] = None


class ProtocolVersion(BaseModel):
    """Protocol version negotiation message.

    Used in WELCOME (coordinator→agent) and CAPABILITIES
    (agent→coordinator) to agree on protocol version.
    """

    protocol_version: str = "2.0"
    server_version: Optional[str] = None
    session_id: Optional[str] = None
