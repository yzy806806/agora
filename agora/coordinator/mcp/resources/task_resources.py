"""MCP Resource: agora://tasks/{task_id}

Returns task details including status, assignee,
dependencies, and artifacts as JSON.
"""
from __future__ import annotations

import json
import logging

from ..deps import get_storage
from ..server import mcp_server

logger = logging.getLogger(__name__)


@mcp_server.resource(
    "agora://tasks/{task_id}",
    name="task-detail",
    title="Task Detail",
    description="Task details including status, assignee, dependencies, artifacts.",
    mime_type="application/json",
)
async def get_task_resource(task_id: str) -> str:
    """Read a single task by ID."""
    storage = get_storage()
    task = await storage.get_task(task_id)
    if task is None:
        return json.dumps({"error": "Task not found", "task_id": task_id})
    # Remove internal fields not useful to MCP clients
    task.pop("task_result", None)
    return json.dumps(task, default=str)
