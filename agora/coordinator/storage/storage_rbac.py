"""Storage mixin: RBAC + Token + Session + Artifact CRUD (dialect-aware)."""
from __future__ import annotations

from typing import Optional

from . import rbac as _rbac
from . import tokens as _tokens
from . import sessions as _sessions
from . import artifacts as _artifacts


class StorageRbacMixin:
    async def get_role(self, name: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _rbac.get_role(db, self.dialect, name)

    async def list_roles(self) -> list[dict]:
        async with self._connection() as db:
            return await _rbac.list_roles(db, self.dialect)

    async def create_rbac_token(
        self, principal_id: str, role: str, token_hash: str,
        token_id: str, scopes: list[str] | None = None,
        expires_at: Optional[str] = None, tenant_id: str = "default",
    ) -> dict:
        async with self._connection() as db:
            return await _rbac.create_token(
                db, self.dialect, principal_id, role, token_hash,
                token_id, scopes, expires_at, tenant_id)

    async def get_rbac_token_by_hash(self, token_hash: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _rbac.get_token_by_hash(
                db, self.dialect, token_hash)

    async def revoke_rbac_token(self, token_id: int) -> None:
        async with self._connection() as db:
            await _rbac.revoke_token(db, self.dialect, token_id)

    async def log_audit(
        self, event_type: str, actor_id: str, action: str,
        resource: Optional[str] = None, actor_role: Optional[str] = None,
        details: Optional[dict] = None, tenant_id: str = "default",
    ) -> int:
        async with self._connection() as db:
            return await _rbac.log_audit(
                db, self.dialect, event_type, actor_id, action,
                resource=resource, actor_role=actor_role,
                details=details, tenant_id=tenant_id)

    async def query_audit(
        self, tenant_id: str = "default",
        actor_id: Optional[str] = None,
        event_type: Optional[str] = None, limit: int = 100,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _rbac.query_audit(
                db, self.dialect, tenant_id=tenant_id,
                actor_id=actor_id, event_type=event_type, limit=limit)


class StorageTokenMixin:
    async def save_token(
        self, token_id: str, token_hash: str,
        principal_id: str, role: str,
        scopes: list[str] | None = None,
        tenant_id: str = "default",
        expires_at: Optional[str] = None,
    ) -> dict:
        async with self._connection() as db:
            return await _tokens.save_token(
                db, self.dialect, token_id, token_hash,
                principal_id, role, scopes,
                tenant_id, expires_at)

    async def get_token(self, token_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _tokens.get_token(db, self.dialect, token_id)

    async def revoke_token(self, token_id: str) -> bool:
        async with self._connection() as db:
            return await _tokens.revoke_token(db, self.dialect, token_id)

    async def list_tokens(
        self, principal_id: Optional[str] = None,
        include_revoked: bool = False,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _tokens.list_tokens(
                db, self.dialect, principal_id=principal_id,
                include_revoked=include_revoked)


class StorageSessionMixin:
    async def create_session(
        self, agent_id: str, project_id: str = "default",
        session_type: str = "task_execution",
        started_at: str | None = None, ended_at: str | None = None,
        input_messages: list | None = None,
        output_messages: list | None = None,
        tool_calls: list | None = None, errors: list | None = None,
        outcome: str = "success", metadata: dict | None = None,
    ) -> dict:
        async with self._connection() as db:
            return await _sessions.create_session(
                db, self.dialect, agent_id,
                project_id=project_id, session_type=session_type,
                started_at=started_at, ended_at=ended_at,
                input_messages=input_messages,
                output_messages=output_messages,
                tool_calls=tool_calls, errors=errors,
                outcome=outcome, metadata=metadata)

    async def get_session(self, sid: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _sessions.get_session(db, self.dialect, sid)

    async def query_sessions(
        self, agent_id: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _sessions.list_sessions(
                db, self.dialect, agent_id=agent_id,
                project_id=project_id, limit=limit, offset=offset)

    async def update_session(self, sid: str, updates: dict) -> Optional[dict]:
        async with self._connection() as db:
            return await _sessions.update_session(
                db, self.dialect, sid, updates)

    async def add_session_note(
        self, sid: str, author: str,
        content: str, tags: list[str] | None = None,
    ) -> Optional[dict]:
        async with self._connection() as db:
            return await _sessions.add_note(
                db, self.dialect, sid, author, content, tags=tags)


class StorageArtifactMixin:
    async def put_artifact(
        self, project_id: str, key: str,
        value: bytes, content_type: str, created_by: str,
    ) -> dict:
        async with self._connection() as db:
            return await _artifacts.put_artifact(
                db, self.dialect, project_id, key,
                value, content_type, created_by)

    async def get_artifact(self, project_id: str, key: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _artifacts.get_artifact(
                db, self.dialect, project_id, key)

    async def delete_artifact(self, project_id: str, key: str) -> bool:
        async with self._connection() as db:
            return await _artifacts.delete_artifact(
                db, self.dialect, project_id, key)

    async def list_artifacts(self, project_id: str) -> list[dict]:
        async with self._connection() as db:
            return await _artifacts.list_artifacts(
                db, self.dialect, project_id)
