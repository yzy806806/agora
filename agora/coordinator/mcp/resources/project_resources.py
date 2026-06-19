"""MCP Resource: agora://projects/{project_id}/overview

Returns project overview including task count, agent list,
and recent activity as JSON.

In Agora, a "project" is identified by project_id used in
pipeline_runs, tasks (via task_graphs), and webhooks.
"""
from __future__ import annotations

import json
import logging

from ..deps import get_storage
from ..server import mcp_server

logger = logging.getLogger(__name__)


@mcp_server.resource(
    "agora://projects/{project_id}/overview",
    name="project-overview",
    title="Project Overview",
    description="Project overview: task count, agent list, recent activity.",
    mime_type="application/json",
)
async def get_project_overview(project_id: str) -> str:
    """Read a project overview by project_id."""
    storage = get_storage()

    # Count pipelines for this project
    pipeline_count = await storage.count_pipeline_runs(
        project_id=project_id)

    # List recent pipelines (limit 5)
    pipelines = await storage.list_pipeline_runs(
        project_id=project_id, limit=5)

    # If no pipelines exist, the project may not exist
    if pipeline_count == 0:
        return json.dumps({
            "error": "Project not found",
            "project_id": project_id,
        })

    # Count agents (all online agents for this project)
    agents = await storage.list_agents(online_only=False)
    agent_count = len(agents)

    # Build overview
    overview = {
        "project_id": project_id,
        "pipeline_count": pipeline_count,
        "agent_count": agent_count,
        "recent_pipelines": [
            {
                "id": p.get("id"),
                "idea": p.get("idea"),
                "phase": p.get("phase"),
                "started_at": p.get("started_at"),
            }
            for p in pipelines
        ],
    }
    return json.dumps(overview, default=str)
