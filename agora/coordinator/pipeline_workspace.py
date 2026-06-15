"""Pipeline-Workspace integration helpers (Phase 14.5a).

Provides functions that bridge the Pipeline execution flow with
WorkspaceManager for file operations at each pipeline phase.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

COORDINATOR_AGENT_ID = "coordinator"


async def ensure_project_root(
    ws: Any, project_id: str,
) -> None:
    """DECOMPOSING phase: create project root dir if not exists."""
    try:
        await ws.mkdir(project_id, "", COORDINATOR_AGENT_ID)
        logger.info("Workspace root ensured for %s", project_id)
    except Exception:
        logger.debug("Workspace root already exists for %s", project_id)


def augment_graph_with_paths(
    graph: dict, artifact_paths: dict[str, list[str]] | None = None,
) -> dict:
    """EXECUTING phase: add workspace_paths to each task in graph.

    artifact_paths maps task_id → list of file paths the task
    is expected to read/write.  If None, workspace_paths stays
    empty and agents discover files at runtime.

    Sets workspace_paths both on the graph dict (for downstream
    consumers) and on each TaskNode object (if present in graph).
    """
    if artifact_paths is None:
        return graph
    task_ids = graph.get("task_ids", [])
    ws_map: dict[str, list[str]] = {}
    for tid in task_ids:
        ws_map[tid] = artifact_paths.get(tid, [])
    graph["workspace_paths"] = ws_map
    # Also set on TaskNode objects if present
    tasks = graph.get("tasks", [])
    for task in tasks:
        paths = ws_map.get(task.id, [])
        if paths:
            task.workspace_paths = paths
    return graph
