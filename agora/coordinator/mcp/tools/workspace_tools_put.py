"""MCP Tool: put_workspace_file (continuation of workspace_tools)."""
from __future__ import annotations

import logging

from ..server import mcp_server

logger = logging.getLogger(__name__)

_MAX_MCP_FILE_SIZE = 1_048_576


@mcp_server.tool()
async def put_workspace_file(
    project_id: str,
    path: str,
    content: str,
    content_type: str = "text/plain",
) -> dict:
    """Write a file to the shared workspace."""
    if len(content.encode()) > _MAX_MCP_FILE_SIZE:
        return {
            "error": "Content too large for MCP (>1MB). Use REST API.",
            "code": 413,
        }
    try:
        from ...workspace.manager import WorkspaceManager
        from ...config import settings as _settings
        from ...workspace.backend import get_storage_backend

        ws_config = {
            "backend": getattr(_settings, "workspace_backend", "local"),
            "local": {"root": getattr(
                _settings, "workspace_root", "./data/workspaces")},
        }
        ws_backend = get_storage_backend(ws_config)
        ws_manager = WorkspaceManager(_settings.get_db_path(), ws_backend)

        agent_id = _get_current_agent_id()
        node = await ws_manager.write_file(
            project_id, path, content.encode("utf-8"),
            agent_id=agent_id, content_type=content_type,
        )
        return {
            "path": path,
            "version": node.version or 1,
            "size": node.size or len(content.encode()),
        }
    except Exception as exc:
        logger.error("put_workspace_file error: %s", exc)
        return {"error": str(exc), "code": 500}


def _get_current_agent_id() -> str:
    """Extract agent_id from MCP context."""
    try:
        ctx = mcp_server.get_context()
        request = ctx.request_context.request
        return getattr(request.state, "agent_id", "unknown")
    except Exception:
        return "unknown"
