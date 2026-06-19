"""Workspace MCP tools: get_workspace_file, put_workspace_file."""
from __future__ import annotations

import logging

from ..deps import get_storage
from ..server import mcp_server

logger = logging.getLogger(__name__)

# Max file size for MCP tool calls (1MB)
_MAX_MCP_FILE_SIZE = 1_048_576


@mcp_server.tool()
async def get_workspace_file(
    project_id: str,
    path: str,
) -> dict:
    """Read a file from the shared workspace."""
    try:
        from ...workspace.manager import WorkspaceManager
        from ...config import settings as _settings
        from ...workspace.backend import get_storage_backend

        ws_config = {
            "backend": getattr(_settings, "workspace_backend", "local"),
            "local": {"root": getattr(_settings, "workspace_root",
                                     "./data/workspaces")},
        }
        ws_backend = get_storage_backend(ws_config)
        ws_manager = WorkspaceManager(_settings.get_db_path(), ws_backend)

        node, data = await ws_manager.read_file(project_id, path, "mcp")
        if node is None:
            return {"error": "File not found", "code": 404}

        content = data.decode("utf-8", errors="replace")
        size = node.size or 0
        if size > _MAX_MCP_FILE_SIZE:
            return {
                "error": "File too large for MCP (>1MB). Use REST API.",
                "code": 413,
            }
        return {
            "path": path,
            "content": content,
            "content_type": node.content_type or "text/plain",
            "size": size,
            "version": node.version or 1,
        }
    except Exception as exc:
        logger.error("get_workspace_file error: %s", exc)
        return {"error": str(exc), "code": 500}


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
            "local": {"root": getattr(_settings, "workspace_root",
                                     "./data/workspaces")},
        }
        ws_backend = get_storage_backend(ws_config)
        ws_manager = WorkspaceManager(_settings.get_db_path(), ws_backend)

        agent_id = _get_current_agent_id()
        node = await ws_manager.write_file(
            project_id, path, content,
            content_type=content_type,
            created_by=agent_id,
        )
        return {
            "path": path,
            "version": getattr(node, "version", 1) or 1,
            "size": getattr(node, "size", len(content)) or len(content),
        }
    except Exception as exc:
        logger.error("put_workspace_file error: %s", exc)
        return {"error": str(exc), "code": 500}


def _get_current_agent_id() -> str | None:
    """Extract agent_id from MCP context."""
    try:
        ctx = mcp_server.get_context()
        request = ctx.request_context.request
        return getattr(request.state, "mcp_agent_id", None)
    except Exception:
        return None
