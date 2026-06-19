"""Storage mixin: Webhook CRUD + trigger history (consolidated)."""
from __future__ import annotations

from typing import Optional

from . import webhooks as _wh


class StorageWebhookMixin:
    async def create_webhook(
        self, project_id: str, name: str, secret_hash: str,
        pipeline_template: dict, description: str = "",
        events: list[str] | None = None, enabled: bool = True,
        allowed_ips: list[str] | None = None,
        max_triggers_per_hour: int = 60,
    ) -> dict:
        async with self._connection() as db:
            return await _wh.create_webhook(
                db, self.dialect, project_id, name,
                secret_hash, pipeline_template,
                description=description, events=events,
                enabled=enabled, allowed_ips=allowed_ips,
                max_triggers_per_hour=max_triggers_per_hour)

    async def get_webhook(self, webhook_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _wh.get_webhook(db, self.dialect, webhook_id)

    async def list_webhooks(
        self, project_id: str | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _wh.list_webhooks(
                db, self.dialect, project_id, limit, offset)

    async def update_webhook(
        self, webhook_id: str, updates: dict,
    ) -> Optional[dict]:
        async with self._connection() as db:
            return await _wh.update_webhook(
                db, self.dialect, webhook_id, updates)

    async def delete_webhook(self, webhook_id: str) -> bool:
        async with self._connection() as db:
            return await _wh.delete_webhook(db, self.dialect, webhook_id)

    async def record_webhook_trigger(
        self, webhook_id: str, event: str, success: bool,
        pipeline_id: str | None = None,
        error: str | None = None, source_ip: str | None = None,
    ) -> dict:
        async with self._connection() as db:
            return await _wh.record_trigger(
                db, self.dialect, webhook_id, event,
                success, pipeline_id=pipeline_id,
                error=error, source_ip=source_ip)

    async def list_webhook_history(
        self, webhook_id: str,
        limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _wh.list_trigger_history(
                db, self.dialect, webhook_id,
                limit=limit, offset=offset)
