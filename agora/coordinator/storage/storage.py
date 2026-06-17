"""Storage facade for the Agora Coordinator service.

Delegates to a StorageBackend and dispatches CRUD operations
to sub-modules.  Accepts either a db_path string (creates
SqliteBackend) or an explicit StorageBackend instance.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from .backend import StorageBackend
from .backend_sqlite import SqliteBackend
from .dialect import Dialect
from . import agents as _agents
from . import agent_heartbeat as _agent_hb
from . import events as _events
from .storage_motion import (
    StorageMotionMixin, StorageMessageMixin, StorageVoteMixin,
)
from .storage_assess import (
    StorageAssessmentMixin, StorageJudgmentMixin, StorageBootstrapMixin,
)
from .storage_event import StorageTaskMixin, StorageParallelMixin
from .storage_rbac import (
    StorageRbacMixin, StorageTokenMixin,
    StorageSessionMixin, StorageArtifactMixin,
)
from .storage_pipeline import (
    StoragePipelineMixin, StorageNotificationMixin, StorageMetricsMixin,
)
from .storage_webhook import StorageWebhookMixin

logger = logging.getLogger(__name__)


class Storage(
    StorageMotionMixin,
    StorageMessageMixin,
    StorageVoteMixin,
    StorageAssessmentMixin,
    StorageJudgmentMixin,
    StorageBootstrapMixin,
    StorageTaskMixin,
    StorageParallelMixin,
    StorageRbacMixin,
    StorageTokenMixin,
    StorageSessionMixin,
    StorageArtifactMixin,
    StoragePipelineMixin,
    StorageNotificationMixin,
    StorageMetricsMixin,
    StorageWebhookMixin,
):
    """Backend-agnostic storage facade."""

    def __init__(self, db_path_or_backend: str | StorageBackend) -> None:
        if isinstance(db_path_or_backend, StorageBackend):
            self._backend = db_path_or_backend
            self.db_path = "<backend>"
        else:
            self._backend = SqliteBackend(db_path_or_backend)
            self.db_path = db_path_or_backend
        self.dialect: Dialect = self._backend.dialect

    @property
    def backend(self) -> StorageBackend:
        return self._backend

    @asynccontextmanager
    async def _connection(self):
        async with self._backend.connection() as conn:
            yield conn

    async def init_db(self) -> None:
        await self._backend.initialize()
        logger.info("Database initialized at %s", self.db_path)

    # --- Agent CRUD (dialect-aware) --

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
    ) -> None:
        async with self._connection() as db:
            await _agents.update_agent_config(
                db, self.dialect, agent_id,
                tpm_limit=tpm_limit,
                tpm_burst_factor=tpm_burst_factor,
                max_concurrent_tasks=max_concurrent_tasks,
                role=role,
                allowed_discussion_roles=allowed_discussion_roles,
            )

    async def update_agent_token(self, agent_id: str, new_token: str) -> None:
        """Replace agent_token in DB (dialect-aware)."""
        async with self._connection() as db:
            sql, params = self.dialect.render(
                "UPDATE agents SET agent_token = ? WHERE agent_id = ?",
                [new_token, agent_id],
            )
            await db.execute(sql, params)
            await db.commit()

    # --- Agent Heartbeat (dialect-aware) --

    async def update_agent_heartbeat(
        self, agent_id: str, load: float = 0.0,
        active_tasks: list[str] | None = None,
    ) -> None:
        async with self._connection() as db:
            await _agent_hb.update_agent_heartbeat(
                db, self.dialect, agent_id, load, active_tasks)

    async def update_agent_capabilities(
        self, agent_id: str, capabilities: list[str],
    ) -> None:
        async with self._connection() as db:
            await _agent_hb.update_agent_capabilities(
                db, self.dialect, agent_id, capabilities)

    async def update_agent_model(self, agent_id: str, model: str) -> None:
        async with self._connection() as db:
            await _agent_hb.update_agent_model(db, self.dialect, agent_id, model)

    async def list_stale_agents(self, timeout_seconds: int = 120) -> list[dict]:
        async with self._connection() as db:
            return await _agent_hb.list_stale_agents(db, self.dialect, timeout_seconds)

    # --- Event CRUD (dialect-aware) --

    async def log_event(self, event_type: str, detail: str = "",
                        motion_id: Optional[str] = None,
                        agent_id: Optional[str] = None) -> int:
        async with self._connection() as db:
            return await _events.log_event(
                db, self.dialect, event_type, detail, motion_id, agent_id)

    async def get_events(self, since: Optional[str] = None,
                         event_type: Optional[str] = None,
                         limit: int = 100) -> list[dict]:
        async with self._connection() as db:
            return await _events.get_events(db, self.dialect, since, event_type, limit)

    async def get_timeline(self, motion_id: str) -> list[dict]:
        async with self._connection() as db:
            return await _events.get_timeline(db, self.dialect, motion_id)
