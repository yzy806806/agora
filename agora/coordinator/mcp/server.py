"""FastMCP server instance + app factory (Phase 16.1).

Creates the FastMCP server with Streamable HTTP transport.
Auth middleware resolves deps lazily from the deps module,
so create_mcp_app() can be called before lifespan init.
"""
from __future__ import annotations

import contextlib
import logging

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp_server = FastMCP(
    "Agora Coordinator",
    instructions=(
        "Agora multi-agent collaboration platform. "
        "Use tools to register agents, manage tasks, "
        "send discussion messages, and access shared workspaces."
    ),
    streamable_http_path="/",
)


@contextlib.asynccontextmanager
async def mcp_lifespan(app):
    """Lifespan context manager for MCP session manager.

    Must be integrated into the main app's lifespan so that
    the StreamableHTTP session manager's task group is initialized.
    """
    session_mgr = mcp_server._session_manager
    if session_mgr is None:
        logger.warning("MCP session manager not initialized")
        yield
        return
    async with session_mgr.run():
        logger.info("MCP session manager started")
        yield
    logger.info("MCP session manager stopped")


def create_mcp_app():
    """Build the MCP ASGI app with auth middleware + health route.

    Returns a Starlette app suitable for FastAPI.mount("/mcp").
    Auth middleware resolves deps lazily at request time.

    IMPORTANT: The caller must integrate mcp_lifespan into the main
    app lifespan, because FastAPI.mount() does not run sub-app lifespans.
    """
    from .auth import MCPAuthMiddleware
    from .health import health_route

    app = mcp_server.streamable_http_app()

    # Add /health route to the MCP app
    app.router.routes.append(health_route)

    # Add auth middleware (resolves deps lazily)
    app.add_middleware(MCPAuthMiddleware)
    logger.info("MCP app created with auth middleware")
    return app
