"""Parallel Execution Coordinator (Phase 10).

Phase 16.10: hub parameter is now optional (None). Agent communication
uses MCP notifications instead of WebSocket.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .task_models import TaskGraph, TaskNode, TaskStatus
from .task_resource import FileResourceTracker
from .task_parallel_helpers import priority_value
from .task_parallel_dispatch import dispatch_ready
from .task_parallel_events import on_task_complete, on_task_failed

logger = logging.getLogger(__name__)


class ParallelExecutionCoordinator:
    """Orchestrates parallel task execution across multiple agents."""

    def __init__(
        self, storage: Any, hub: Any = None,
        resource_tracker: FileResourceTracker | None = None,
    ) -> None:
        self.storage = storage
        self.hub = hub  # None: MCP replaces WS
        self.runqueue: asyncio.PriorityQueue[tuple[int, str]] = asyncio.PriorityQueue()
        self.agent_slots: dict[str, int] = {}
        self.resource_tracker = resource_tracker or FileResourceTracker()
        self._running_futures: dict[str, asyncio.Task] = {}
        self._graph_tasks: dict[str, TaskNode] = {}
        self._completed: set[str] = set()
        self._failed: set[str] = set()
        self._result: dict[str, Any] = {}

    async def execute_graph(self, graph: TaskGraph) -> dict:
        """Execute all tasks in parallel where dependencies allow."""
        self._graph_tasks = {t.id: t for t in graph.tasks}
        self._completed, self._failed, self._running_futures = set(), set(), {}
        self._result = {"graph_id": graph.id, "completed": [], "failed": [], "blocked": []}
        for task in graph.tasks:
            if not task.depends_on:
                await self.runqueue.put((priority_value(task), task.id))
        while not self._all_done(graph):
            await dispatch_ready(
                self._graph_tasks, self.runqueue, self.storage,
                self.hub, self.agent_slots, self.resource_tracker,
                self._result, self._running_futures)
            if not self._running_futures:
                self._mark_blocked(graph); break
            done, _ = await asyncio.wait(
                list(self._running_futures.values()),
                return_when=asyncio.FIRST_COMPLETED)
            for fut in done:
                await self._process_future(fut)
        return self._result

    async def _process_future(self, fut: asyncio.Task) -> None:
        tid = next((k for k, v in self._running_futures.items() if v is fut), None)
        if not tid:
            return
        self._running_futures.pop(tid, None)
        try:
            await fut
            await on_task_complete(
                tid, self._graph_tasks, self._completed,
                self._failed, self._result, self.agent_slots,
                self.resource_tracker, self.runqueue)
        except Exception as exc:
            await on_task_failed(
                tid, str(exc), self._graph_tasks,
                self._failed, self._result, self.agent_slots,
                self.resource_tracker)

    def _all_done(self, graph: TaskGraph) -> bool:
        return all(t.id in self._completed or t.id in self._failed for t in graph.tasks)

    def _mark_blocked(self, graph: TaskGraph) -> None:
        for t in graph.tasks:
            if t.id not in self._completed and t.id not in self._failed:
                self._result["blocked"].append(t.id)
