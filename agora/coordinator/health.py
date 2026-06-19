"""Health check endpoint for the Agora Coordinator.

GET /api/v1/health — no auth required, for Docker healthcheck.
Returns: status, version, uptime_seconds, agents_connected, tenants, db_size_mb.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import APIRouter, Request

from .config import settings

# Simple start time for uptime calculation (replaces observability.metrics._START_TIME)
_START_TIME = time.time()

router = APIRouter(tags=["health"])

from agora import __version__ as _VERSION


@router.get("/health")
async def health_check(request: Request) -> dict:
    """Return coordinator health status (no auth required)."""
    app_state = request.app.state

    # Uptime
    uptime = round(time.time() - _START_TIME, 1)

    # Connected agents from storage
    agents_connected = 0
    storage = getattr(app_state, "storage", None)
    if storage is not None:
        try:
            agents = await storage.list_agents()
            agents_connected = sum(1 for a in agents if a.get("is_online"))
        except Exception:
            agents_connected = 0

    # Tenant count from TenantManager
    tenants = 0
    tenant_mgr = getattr(app_state, "tenant_mgr", None)
    if tenant_mgr is not None:
        try:
            tenants = len(await tenant_mgr.list_tenants())
        except Exception:
            tenants = 0

    # DB size in MB
    db_size_mb = 0.0
    db_path = Path(settings.db_path)
    if db_path.exists():
        db_size_mb = round(
            os.path.getsize(str(db_path)) / (1024 * 1024), 2
        )

    return {
        "status": "healthy",
        "version": _VERSION,
        "uptime_seconds": uptime,
        "agents_connected": agents_connected,
        "tenants": tenants,
        "db_size_mb": db_size_mb,
    }
