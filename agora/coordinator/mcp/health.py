"""MCP health check endpoint.

Provides /mcp/health for Docker healthchecks and
MCP client initialization probes.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


async def mcp_health(request: Request) -> JSONResponse:
    """Health check for the MCP endpoint (no auth required)."""
    return JSONResponse({
        "status": "healthy",
        "service": "agora-mcp",
        "protocol": "streamable-http",
    })


# Route to be included in the MCP Starlette app
health_route = Route("/health", mcp_health)
