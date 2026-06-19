"""Storage mixin: MCP session persistence — Phase 16.4c."""
from __future__ import annotations

from typing import Optional

from ..mcp import storage_mcp as _mcp


class StorageMcpMixin:
    """MCP session CRUD methods (dialect-aware)."""

    async def upsert_mcp_session(
        self, mcp_session_id: str, agent_id: str,
        transport_type: str = "streamable-http",
    ) -> None:
        async with self._connection() as db:
            await _mcp.upsert_mcp_session(
                db, self.dialect, mcp_session_id,
                agent_id, transport_type,
            )

    async def get_mcp_session_by_agent(
        self, agent_id: str,
    ) -> Optional[dict]:
        async with self._connection() as db:
            return await _mcp.get_mcp_session_by_agent(
                db, self.dialect, agent_id,
            )

    async def get_mcp_session_by_id(
        self, mcp_session_id: str,
    ) -> Optional[dict]:
        async with self._connection() as db:
            return await _mcp.get_mcp_session_by_id(
                db, self.dialect, mcp_session_id,
            )

    async def update_mcp_session_activity(
        self, mcp_session_id: str,
    ) -> None:
        async with self._connection() as db:
            await _mcp.update_mcp_session_activity(
                db, self.dialect, mcp_session_id,
            )

    async def delete_mcp_session(
        self, mcp_session_id: str,
    ) -> None:
        async with self._connection() as db:
            await _mcp.delete_mcp_session(
                db, self.dialect, mcp_session_id,
            )

    async def delete_stale_mcp_sessions(
        self, timeout_seconds: int = 300,
    ) -> int:
        async with self._connection() as db:
            return await _mcp.delete_stale_mcp_sessions(
                db, self.dialect, timeout_seconds,
            )
