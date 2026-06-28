"""Storage mixin: Task + Parallel CRUD (dialect-aware)."""
from __future__ import annotations

from typing import Optional

from . import tasks as _tasks
from . import parallel as _parallel


class StorageTaskMixin:
    async def create_task_graph(self, graph_id: str, motion_id: Optional[str] = None,
                                parallel_mode: str = "auto",
                                max_parallel_slots: int = 10,
                                resource_conflict_policy: str = "warn") -> dict:
        async with self._connection() as db:
            return await _tasks.create_task_graph(
                db, self.dialect, graph_id, motion_id,
                parallel_mode=parallel_mode,
                max_parallel_slots=max_parallel_slots,
                resource_conflict_policy=resource_conflict_policy)

    async def get_task_graph(self, graph_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _tasks.get_task_graph(db, self.dialect, graph_id)

    async def list_task_graphs(self, limit: int = 100, offset: int = 0) -> list[dict]:
        async with self._connection() as db:
            return await _tasks.list_task_graphs(
                db, self.dialect, limit, offset)

    async def get_task_graph_by_motion(self, motion_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _tasks.get_task_graph_by_motion(
                db, self.dialect, motion_id)

    async def create_task(self, task) -> dict:
        async with self._connection() as db:
            return await _tasks.create_task(db, self.dialect, task)

    async def get_task(self, task_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _tasks.get_task(db, self.dialect, task_id)

    async def list_tasks(self, **kwargs) -> list[dict]:
        async with self._connection() as db:
            return await _tasks.list_tasks(db, self.dialect, **kwargs)

    async def update_task_status(self, task_id: str, status: str, **kwargs) -> None:
        async with self._connection() as db:
            await _tasks.update_task_status(
                db, self.dialect, task_id, status, **kwargs)

    async def get_agent_task_count(self, agent_id: str, active_only: bool = True) -> int:
        async with self._connection() as db:
            return await _tasks.get_agent_task_count(
                db, self.dialect, agent_id, active_only)

    async def save_task_result(self, task_id: str, result_json: str) -> None:
        async with self._connection() as db:
            await _tasks.save_task_result(
                db, self.dialect, task_id, result_json)

    async def get_task_result(self, task_id: str) -> dict | None:
        async with self._connection() as db:
            return await _tasks.get_task_result(
                db, self.dialect, task_id)


class StorageParallelMixin:
    async def create_execution_slot(self, slot) -> dict:
        async with self._connection() as db:
            return await _parallel.create_execution_slot(
                db, self.dialect, slot)

    async def get_execution_slots(
        self, agent_id: str | None = None, status: str | None = None,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _parallel.get_execution_slots(
                db, self.dialect, agent_id=agent_id, status=status)

    async def update_slot_status(self, task_id: str, status: str) -> None:
        async with self._connection() as db:
            await _parallel.update_slot_status(
                db, self.dialect, task_id, status)

    async def delete_execution_slot(self, task_id: str) -> None:
        async with self._connection() as db:
            await _parallel.delete_execution_slot(
                db, self.dialect, task_id)

    async def acquire_resource_lock(self, lock) -> dict:
        async with self._connection() as db:
            return await _parallel.acquire_resource_lock(
                db, self.dialect, lock)

    async def get_resource_lock(self, resource_path: str) -> dict | None:
        async with self._connection() as db:
            return await _parallel.get_resource_lock(
                db, self.dialect, resource_path)

    async def get_locks_by_task(self, task_id: str) -> list[dict]:
        async with self._connection() as db:
            return await _parallel.get_locks_by_task(
                db, self.dialect, task_id)

    async def add_waiting_task(self, resource_path: str, task_id: str) -> None:
        async with self._connection() as db:
            await _parallel.add_waiting_task(
                db, self.dialect, resource_path, task_id)

    async def release_resource_lock(self, resource_path: str) -> None:
        async with self._connection() as db:
            await _parallel.release_resource_lock(
                db, self.dialect, resource_path)

    async def release_all_locks_for_task(self, task_id: str) -> None:
        async with self._connection() as db:
            await _parallel.release_all_locks_for_task(
                db, self.dialect, task_id)
