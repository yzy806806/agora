"""Task Generator — convert discussion results into Agora tasks.

Backend-agnostic: creates tasks via Agora's own Task API,
not tied to Hermes kanban or any specific agent framework.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# Category → default assignee mapping (maps to registered agent roles)
ASSIGNEE_MAP: dict[str, str] = {
    "development": "developer",
    "review": "reviewer",
    "research": "architect",
    "release": "developer",
    "documentation": "developer",
    "architecture": "architect",
}


@dataclass
class TaskSpec:
    """Specification for a task to be created."""
    title: str
    description: str
    assignee: str
    priority: str = "normal"  # low | normal | high | critical
    required_capabilities: list[str] = field(default_factory=list)


class TaskGenerator:
    """Generate Agora tasks from discussion results.

    Uses Agora's POST /api/v1/tasks endpoint — works with any
    agent backend (Hermes, OpenCode, etc).
    """

    def __init__(self, coordinator_url: str = "http://localhost:8765") -> None:
        self.coordinator_url = coordinator_url.rstrip("/")

    async def generate_tasks(
        self,
        discussion_result: dict,
        graph_id: Optional[str] = None,
    ) -> list[str]:
        """Create Agora tasks from a discussion result's action_items."""
        task_ids: list[str] = []
        action_items = discussion_result.get("action_items", [])
        for idx, item in enumerate(action_items):
            category = item.get("category", "development")
            priority_map = {0: "normal", 1: "high", 2: "critical"}
            priority = item.get("priority", "normal")
            if isinstance(priority, int):
                priority = priority_map.get(priority, "normal")
            spec = TaskSpec(
                title=item.get("title", f"Task {idx + 1}"),
                description=item.get("description", ""),
                assignee=self._infer_assignee(category),
                priority=priority,
                required_capabilities=item.get("skills", []),
            )
            task_id = await self._create_task(spec, graph_id)
            task_ids.append(task_id)
        logger.info("Generated %d tasks from discussion", len(task_ids))
        return task_ids

    async def from_discussion_result(
        self,
        result: "DiscussionResult",  # noqa: F821
        graph_id: Optional[str] = None,
    ) -> list[str]:
        """Generate tasks from a DiscussionResult object."""
        payload = {
            "action_items": result.recommended_actions,
        }
        return await self.generate_tasks(payload, graph_id)

    async def _create_task(
        self, spec: TaskSpec, graph_id: Optional[str] = None,
    ) -> str:
        """Create a single Agora task via the Task API."""
        payload: dict = {
            "title": spec.title,
            "description": spec.description,
            "assigned_to": spec.assignee,
            "priority": spec.priority,
        }
        if graph_id:
            payload["graph_id"] = graph_id
        if spec.required_capabilities:
            payload["required_capabilities"] = spec.required_capabilities
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.coordinator_url}/api/v1/tasks",
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    return data["id"]
        except aiohttp.ClientError as exc:
            logger.error("Task creation failed: %s", exc)
            raise RuntimeError(f"Task creation failed: {exc}") from exc

    def _infer_assignee(self, category: str) -> str:
        """Map a category to a default assignee role."""
        return ASSIGNEE_MAP.get(category, "developer")

    async def create_approval_task(
        self, motion_id: str, decision: str,
    ) -> str:
        """Create a user-approval task."""
        spec = TaskSpec(
            title=f"[审批] 讨论结果 {motion_id}",
            description=f"请审批开发方向讨论结果：{decision}",
            assignee="user",
            priority="critical",
        )
        return await self._create_task(spec)
