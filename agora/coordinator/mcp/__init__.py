"""MCP Server integration for Agora Coordinator.

Exposes Agora's agent, task, and discussion APIs as MCP tools,
resources, and notifications via the Streamable HTTP transport.
"""
# Import server first (creates mcp_server instance)
from .server import mcp_server, create_mcp_app

# Then import tool modules to register their @mcp_server.tool() decorators
from .tools import (  # noqa: F401
    agent_tools, task_tools, comm_tools, workspace_tools,
)

__all__ = ["mcp_server", "create_mcp_app"]
