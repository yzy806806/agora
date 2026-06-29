"""Storage mixin: Agent CRUD methods (dialect-aware)."""
from __future__ import annotations

from typing import Optional

from . import agents as _agents


class StorageAgentMixin:
    """Agent-related Storage methods."""

    async def register_agent(self, agent_id: str, name: str,
                             model: str = "unknown",
                             capabilities: list[str] | None = None,
                             role: str = "participant",
                             agent_type: str = "hermes",
                             max_concurrent_tasks: int = 2,
                             agent_token: str = "",
                             is_approved: bool = False,
                             approval_status: str = "pending",
                             tpm_limit: int = 10000,
                             tpm_burst_factor: float = 1.5,
                             **kwargs) -> dict:
        async with self._connection() as db:
            return await _agents.register_agent(
                db, self.dialect, agent_id, name, model,
                capabilities=capabilities, role=role,
                agent_type=agent_type,
                max_concurrent_tasks=max_concurrent_tasks,
                agent_token=agent_token,
                is_approved=is_approved,
                approval_status=approval_status,
                tpm_limit=tpm_limit,
                tpm_burst_factor=tpm_burst_factor,
            )

    async def get_agent(self, agent_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _agents.get_agent(db, self.dialect, agent_id)

    async def get_agent_by_token(self, token: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _agents.get_agent_by_token(db, self.dialect, token)

    async def find_agent_by_name(self, name: str) -> Optional[dict]:
        """Find an agent by name (for idempotent re-registration)."""
        async with self._connection() as db:
            return await _agents.find_agent_by_name(db, self.dialect, name)

    async def list_agents(self, online_only: bool = False) -> list[dict]:
        async with self._connection() as db:
            return await _agents.list_agents(db, self.dialect, online_only)

    async def set_agent_online(self, agent_id: str, online: bool) -> None:
        async with self._connection() as db:
            await _agents.set_agent_online(db, self.dialect, agent_id, online)

    async def deregister_agent(self, agent_id: str) -> None:
        async with self._connection() as db:
            await _agents.deregister_agent(db, self.dialect, agent_id)

    async def set_agent_approval(
        self, agent_id: str, is_approved: bool, approval_status: str,
    ) -> None:
        async with self._connection() as db:
            await _agents.set_agent_approval(
                db, self.dialect, agent_id, is_approved, approval_status)

    async def update_agent_tpm_config(
        self, agent_id: str,
        tpm_limit: int | None = None,
        tpm_burst_factor: float | None = None,
    ) -> None:
        async with self._connection() as db:
            await _agents.update_agent_tpm_config(
                db, self.dialect, agent_id, tpm_limit, tpm_burst_factor)

    async def update_agent_config(
        self, agent_id: str, *,
        tpm_limit: int | None = None,
        tpm_burst_factor: float | None = None,
        max_concurrent_tasks: int | None = None,
        role: str | None = None,
        allowed_discussion_roles: list[str] | None = None,
        capabilities: list[str] | None = None,
        matrix_user_id: str | None = None,
    ) -> None:
        async with self._connection() as db:
            if capabilities is not None:
                import json
                caps_json = json.dumps(capabilities)
                sql, params = self.dialect.render(
                    "UPDATE agents SET capabilities = ? WHERE agent_id = ?",
                    [caps_json, agent_id])
                await db.execute(sql, params)
                await db.commit()
            if matrix_user_id is not None:
                sql, params = self.dialect.render(
                    "UPDATE agents SET matrix_user_id = ? WHERE agent_id = ?",
                    [matrix_user_id, agent_id])
                await db.execute(sql, params)
                await db.commit()
            await _agents.update_agent_config(
                db, self.dialect, agent_id,
                tpm_limit=tpm_limit,
                tpm_burst_factor=tpm_burst_factor,
                max_concurrent_tasks=max_concurrent_tasks,
                role=role,
                allowed_discussion_roles=allowed_discussion_roles,
            )

    async def update_agent_token(
        self, agent_id: str, new_token: str,
    ) -> None:
        async with self._connection() as db:
            sql, params = self.dialect.render(
                "UPDATE agents SET agent_token = ? WHERE agent_id = ?",
                [new_token, agent_id])
            await db.execute(sql, params)
            await db.commit()

    async def clear_registration_token(self, agent_id: str) -> None:
        """Clear registration_token after one-time agent_token retrieval."""
        async with self._connection() as db:
            await _agents.clear_registration_token(db, self.dialect, agent_id)
