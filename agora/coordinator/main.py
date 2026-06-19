"""FastAPI application entry point for the Agora Coordinator service.

Assembles all modules, configures middleware, and provides lifespan
management (DB init on startup, cleanup on shutdown).
"""
from __future__ import annotations

import asyncio
import logging

from agora import __version__
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .tenant.router import router as tenant_router
from .tenant.router import init_tenant_deps
from .tenant.manager import TenantManager
from .storage.storage_manager import StorageManager
from .config import settings
from .router import init_deps, router
from .state import StateMachine
from .storage import Storage
from .storage.backend_postgres import PostgresBackend
from .heartbeat import HeartbeatManager
from .timeout_checker import heartbeat_timeout_checker
from .timeout import TimeoutConfig, TimeoutManager
from .bootstrap import BootstrapConfig, BootstrapEngine
from .bootstrap.routes import router as bootstrap_router
from .bootstrap.routes_extra import router as bootstrap_extra_router
from .dashboard import router as dashboard_router
from .dashboard import init_dashboard_deps, init_audit_deps
from .rate_limiter import TokenRateLimiter
from .rate_limit_flush import rate_limit_flush_task
from .rate_limit_router import router as rate_limit_router
from .rate_limit_router import init_rate_limit_deps
from .rbac_middleware import RBACMiddleware
from .task_parallel import ParallelExecutionCoordinator
from .task_resource import FileResourceTracker
from .token_manager import TokenManager
from .audit import AuditLogger
from .dashboard_ws import dashboard_hub
from .dashboard_ws_endpoint import dashboard_ws_endpoint
from .auth_router import router as auth_router
from .auth_router import init_auth_deps
from .event_bus import init_event_bus, init_mcp_bridge
# Phase 16.1: MCP Server
from .mcp.deps import init_mcp_deps
from .mcp.server import create_mcp_app
# Phase 16.4: MCP SSE Notification Bridge
from .mcp.session_map import MCPSessionMap
from .mcp.notifications import MCPNotificationBridge
from .agent_config_routes import router as agent_config_router
from .agent_config_routes import init_agent_config_deps
from .metrics_history_router import router as metrics_history_router
from .metrics_history_router import init_metrics_history_deps
from .health import router as health_router
from .notification_router import router as notification_router
from .notification_router import init_notification_router_deps
from .pipeline_router import router as pipeline_router
from .pipeline_router import init_pipeline_router_deps
from .webhook import crud_router as webhook_router
from .webhook import trigger_router as webhook_trigger_router
from .webhook import init_webhook_router_deps, init_webhook_trigger_deps
from .discovery_router import router as discovery_router
from .discovery_router import init_discovery_deps
from .task_action_router import router as task_action_router
from .task_action_router import init_task_action_deps
from .workspace.workspace_router import router as workspace_router
from .workspace.workspace_router_read import router_read as workspace_router_read
from .workspace.workspace_router_dirs import router_dirs as workspace_router_dirs
from .workspace.workspace_router_locks import router_locks as workspace_router_locks
from .workspace.workspace_router_bulk import router_bulk as workspace_router_bulk
from .workspace.workspace_router import init_workspace_router_deps
from .workspace.backend import get_storage_backend
from .workspace.manager import WorkspaceManager
from .trace_context import set_trace_id, get_trace_id

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: init DB on startup, cleanup on shutdown."""
    db_backend = settings.database.resolved_backend()
    if db_backend == "postgres":
        pg_url = settings.database.resolved_url()
        if not pg_url:
            raise RuntimeError(
                "Postgres backend selected but no database_url configured"
            )
        storage = Storage(PostgresBackend(
            database_url=pg_url,
            pool_min_size=settings.database.pool_min_size,
            pool_max_size=settings.database.pool_max_size,
            pool_acquire_timeout=settings.database.pool_acquire_timeout,
        ))
    else:
        db_dir = os.path.dirname(settings.get_db_path())
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        storage = Storage(settings.get_db_path())
    await storage.init_db()
    data_dir = Path(os.path.dirname(settings.get_db_path()) or "data")
    storage_mgr = StorageManager(data_dir)
    await storage_mgr.init()
    tenant_mgr = TenantManager(storage_mgr)
    init_tenant_deps(tenant_mgr)
    app.state.storage_mgr = storage_mgr
    app.state.tenant_mgr = tenant_mgr
    state_machine = StateMachine(storage)
    init_deps(storage, state_machine)
    init_discovery_deps(storage)
    init_task_action_deps(storage)
    # Broadcast bus (Phase 14+.B.3)
    from .broadcast_bus import LocalBus
    from .broadcast_bus_redis import RedisBus
    bus = None
    if settings.redis_url and settings.broadcast_backend == "redis":
        bus = RedisBus(settings.redis_url)
        await bus.connect()
        logger.info("Broadcast bus: RedisBus (%s)", settings.redis_url)
    else:
        bus = LocalBus()
        logger.info("Broadcast bus: LocalBus (in-process)")
    app.state.bus = bus
    # Dashboard deps init
    init_dashboard_deps(storage)
    # Bootstrap engine init
    bootstrap_cfg = BootstrapConfig(db_path=settings.get_db_path())
    bootstrap_engine = BootstrapEngine(bootstrap_cfg)
    bootstrap_engine.init_routes()
    # Token rate limiter init
    token_limiter = TokenRateLimiter()
    app.state.token_limiter = token_limiter
    init_rate_limit_deps(storage, token_limiter)
    rl_flush_task = asyncio.create_task(
        rate_limit_flush_task(token_limiter, storage)
    )
    # Heartbeat & Timeout init
    heartbeat_mgr = HeartbeatManager()
    timeout_cfg = TimeoutConfig(
        round_timeout=settings.round_timeout_seconds,
        vote_timeout=settings.vote_timeout_seconds,
        discussion_timeout=settings.discussion_timeout_seconds,
    )
    timeout_mgr = TimeoutManager(config=timeout_cfg)
    app.state.heartbeat_mgr = heartbeat_mgr
    app.state.timeout_mgr = timeout_mgr
    await heartbeat_mgr.start_heartbeat(
        interval=settings.heartbeat_interval_seconds,
    )
    # Heartbeat timeout checker
    hb_timeout_task = asyncio.create_task(
        heartbeat_timeout_checker(
            storage,
            interval=settings.heartbeat_interval_seconds,
            timeout=settings.heartbeat_timeout_seconds,
        )
    )
    # TokenManager + AuditLogger (Phase 10.2)
    token_mgr = TokenManager(secret=settings.jwt_secret or None)
    audit_logger = AuditLogger(settings.get_db_path())
    app.state.token_mgr = token_mgr
    app.state.audit_logger = audit_logger
    init_audit_deps(audit_logger)
    # Dashboard WS hub init
    dashboard_hub.set_token_manager(token_mgr)
    # Auth deps + event bus init
    init_auth_deps(token_mgr)
    init_event_bus(dashboard_hub)
    # Phase 16.4: MCP SSE Notification Bridge
    _mcp_session_map = MCPSessionMap()
    _mcp_bridge = MCPNotificationBridge(_mcp_session_map, storage)
    init_mcp_bridge(_mcp_bridge)
    # Agent config deps
    init_agent_config_deps(storage, token_mgr)
    # Notification router deps
    init_notification_router_deps(storage)
    # Pipeline router deps
    init_pipeline_router_deps(storage)
    # Webhook router deps
    init_webhook_router_deps(storage)
    init_webhook_trigger_deps(storage)
    # Workspace manager + router init
    ws_config = {
        "backend": getattr(settings, "workspace_backend", "local"),
        "local": {"root": getattr(settings, "workspace_root", "./data/workspaces")},
    }
    ws_backend = get_storage_backend(ws_config)
    ws_manager = WorkspaceManager(settings.get_db_path(), ws_backend)
    init_workspace_router_deps(ws_manager)
    app.state.ws_manager = ws_manager
    # Phase 16.1: MCP Server deps
    init_mcp_deps(storage, token_mgr=token_mgr, ws_manager=ws_manager)
    # Metrics history deps
    init_metrics_history_deps(storage)
    # Parallel execution coordinator (hub=None: MCP replaces WS)
    resource_tracker = FileResourceTracker()
    parallel_coord = ParallelExecutionCoordinator(
        storage, None, resource_tracker,
    )
    app.state.parallel_coord = parallel_coord
    app.state.resource_tracker = resource_tracker
    logger.info("Coordinator started (backend=%s)", db_backend)
    yield
    # Cleanup
    bus = getattr(app.state, "bus", None)
    if bus:
        await bus.close()
    if rl_flush_task is not None:
        rl_flush_task.cancel()
        try:
            await rl_flush_task
        except asyncio.CancelledError:
            pass
        logger.info("Rate limit flush task stopped")
    if hb_timeout_task is not None:
        hb_timeout_task.cancel()
        try:
            await hb_timeout_task
        except asyncio.CancelledError:
            pass
        logger.info("Heartbeat timeout checker stopped")
    await heartbeat_mgr.stop()
    logger.info("Coordinator shutting down")


def create_app() -> FastAPI:
    """Factory: create and configure the FastAPI application."""
    app = FastAPI(
        title="Hermes Agora Coordinator",
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RBACMiddleware)

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        """Inject X-Trace-Id into every HTTP request context."""
        trace_id = request.headers.get(
            "X-Trace-Id", str(uuid.uuid4()))
        set_trace_id(trace_id)
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response
    app.include_router(tenant_router, prefix="/api/v1")
    app.include_router(router, prefix="/api/v1")
    app.include_router(bootstrap_router, prefix="/api/v1")
    app.include_router(bootstrap_extra_router, prefix="/api/v1")
    app.include_router(dashboard_router, prefix="/api/v1")
    app.include_router(rate_limit_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(agent_config_router, prefix="/api/v1")
    app.include_router(notification_router, prefix="/api/v1")
    app.include_router(pipeline_router, prefix="/api/v1")
    app.include_router(metrics_history_router, prefix="/api/v1")
    app.include_router(workspace_router, prefix="/api/v1")
    app.include_router(workspace_router_read, prefix="/api/v1")
    app.include_router(workspace_router_dirs, prefix="/api/v1")
    app.include_router(workspace_router_locks, prefix="/api/v1")
    app.include_router(workspace_router_bulk, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(discovery_router, prefix="/api/v1")
    app.include_router(webhook_router, prefix="/api/v1")
    app.include_router(webhook_trigger_router, prefix="/api/v1")
    app.include_router(task_action_router, prefix="/api/v1")
    # Dashboard WebSocket endpoint
    app.add_api_websocket_route("/ws/dashboard", dashboard_ws_endpoint)
    # Dashboard static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/login")
    async def login_page():
        """Phase 15.A: Independent login page."""
        from fastapi.responses import FileResponse
        return FileResponse(static_dir / "login.html")

    @app.get("/dashboard")
    async def dashboard_page(request: Request):
        """Phase 15.A: Dashboard page — requires valid JWT."""
        from fastapi.responses import FileResponse, RedirectResponse
        token = request.cookies.get("dashboard_token")
        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header.removeprefix("Bearer ").strip()
        if token:
            token_mgr = getattr(app.state, "token_mgr", None)
            if token_mgr:
                try:
                    token_mgr.validate_token(token)
                    return FileResponse(static_dir / "dashboard.html")
                except ValueError:
                    pass
        return RedirectResponse(url="/login", status_code=302)

    # Legacy /health redirect (backward compat)
    @app.get("/health")
    async def health_legacy():
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/api/v1/health")

    # Phase 16.1: Mount MCP Server at /mcp
    mcp_app = create_mcp_app()
    app.mount("/mcp", mcp_app)

    return app


app = create_app()


def main() -> None:
    """Run the coordinator service via uvicorn."""
    uvicorn.run(
        "agora.coordinator.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
