"""Pipeline-Workspace: review + release phase helpers (Phase 14.5a).

REVIEWING phase: pull changed files from workspace for reviewer.
RELEASING phase: pull files for releaser to commit to git.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def collect_workspace_changed_files(
    ws: Any, project_id: str, graph: dict,
) -> list[str]:
    """REVIEWING phase: list all files changed during execution.

    Uses WorkspaceManager.list_dir(recursive=True) to discover
    all files in the project workspace.  Returns path list.
    """
    try:
        nodes = await ws.list_dir(project_id, "", recursive=True)
        paths = [n.path for n in nodes if n.file_type.value == "file"]
        logger.info(
            "Workspace has %d files for review in %s",
            len(paths), project_id,
        )
        return paths
    except Exception:
        logger.warning("Failed to list workspace files for review")
        return graph.get("changed_files", [])


async def pull_workspace_files(
    ws: Any, project_id: str, paths: list[str],
) -> dict[str, bytes]:
    """RELEASING phase: pull all changed files for git commit.

    Returns {path: content} dict.  Skips missing files.
    """
    try:
        files = await ws.pull_files(project_id, paths, "releaser")
        logger.info(
            "Pulled %d/%d files for release in %s",
            len(files), len(paths), project_id,
        )
        return files
    except Exception:
        logger.warning("Failed to pull workspace files for release")
        return {}
