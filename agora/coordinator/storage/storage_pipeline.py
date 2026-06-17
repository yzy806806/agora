"""Storage mixin: Pipeline + Notification + Metrics (all dialect-aware)."""
from __future__ import annotations

from typing import Optional

from . import pipelines as _pipelines
from . import notifications as _notifications


class StoragePipelineMixin:
    async def create_pipeline_run(
        self, project_id: str, idea: str,
        phase: str = "discussing",
        motion_id: str | None = None, graph_id: str | None = None,
    ) -> dict:
        async with self._connection() as db:
            return await _pipelines.create_pipeline_run(
                db, self.dialect, project_id, idea, phase,
                motion_id, graph_id)

    async def get_pipeline_run(self, run_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _pipelines.get_pipeline_run(
                db, self.dialect, run_id)

    async def list_pipeline_runs(
        self, project_id: str | None = None,
        phase: str | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _pipelines.list_pipeline_runs(
                db, self.dialect, project_id=project_id,
                phase=phase, limit=limit, offset=offset)

    async def update_pipeline_run(
        self, run_id: str, updates: dict,
    ) -> Optional[dict]:
        async with self._connection() as db:
            return await _pipelines.update_pipeline_run(
                db, self.dialect, run_id, updates)

    async def delete_pipeline_run(self, run_id: str) -> bool:
        async with self._connection() as db:
            return await _pipelines.delete_pipeline_run(
                db, self.dialect, run_id)

    async def count_pipeline_runs(
        self, project_id: str | None = None,
        phase: str | None = None,
    ) -> int:
        async with self._connection() as db:
            return await _pipelines.count_pipeline_runs(
                db, self.dialect, project_id=project_id, phase=phase)


class StorageNotificationMixin:
    async def create_notification(
        self, type: str, title: str, body: str,
        project_id: str, priority: str = "medium",
    ) -> dict:
        async with self._connection() as db:
            return await _notifications.create_notification(
                db, self.dialect, type, title, body,
                project_id, priority)

    async def get_notification(self, notif_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _notifications.get_notification(
                db, self.dialect, notif_id)

    async def list_notifications(
        self, project_id: str | None = None,
        unread_only: bool = False,
        priority: str | None = None,
        limit: int = 50, offset: int = 0,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _notifications.list_notifications(
                db, self.dialect, project_id=project_id,
                unread_only=unread_only, priority=priority,
                limit=limit, offset=offset)

    async def count_notifications(
        self, project_id: str | None = None,
        unread_only: bool = False,
        priority: str | None = None,
    ) -> tuple[int, int]:
        async with self._connection() as db:
            return await _notifications.count_notifications(
                db, self.dialect, project_id=project_id,
                unread_only=unread_only, priority=priority)

    async def mark_notification_read(self, notif_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _notifications.mark_read(
                db, self.dialect, notif_id)

    async def mark_all_notifications_read(
        self, project_id: str | None = None,
    ) -> int:
        async with self._connection() as db:
            return await _notifications.mark_all_read(
                db, self.dialect, project_id=project_id)


class StorageMetricsMixin:
    async def query_metrics_history(
        self, func_name: str, range_key: str,
        project_id: str | None = None,
    ) -> dict:
        from . import metrics_history as _mh
        from . import metrics_history_extra as _mhe
        from . import metrics_history_pipeline as _mhp
        func_map = {
            "query_agent_activity": _mh.query_agent_activity,
            "query_task_throughput": _mh.query_task_throughput,
            "query_discussion_outcomes": _mhe.query_discussion_outcomes,
            "query_pipeline_success_rate": _mhp.query_pipeline_success_rate,
            "query_rate_limit_usage": _mhp.query_rate_limit_usage,
        }
        func = func_map.get(func_name)
        if func is None:
            return {"labels": [], "datasets": []}
        async with self._connection() as db:
            return await func(db, self.dialect, range_key,
                              project_id=project_id)
