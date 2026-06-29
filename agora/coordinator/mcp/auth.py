"""MCP authentication middleware (Phase 16.1).

Validates Bearer tokens on MCP requests independently from
the FastAPI RBACMiddleware, since /mcp is mounted as a
separate Starlette sub-app that bypasses FastAPI middleware.

Token resolution order:
1. Admin token fallback → role=admin
2. JWT Bearer token → decode role + agent_id claims
3. Agent token (ag-*) → lookup agent_id from Storage

Supports two modes:
- Constructor injection (token_mgr, admin_token, storage) for testing
- Lazy deps module resolution for production (when args are None)
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..rbac import Role

logger = logging.getLogger(__name__)

# Paths under /mcp that don't require authentication
MCP_AUTH_WHITELIST: list[str] = ["/mcp/health"]

# State keys injected by this middleware
_MCP_AGENT_ID = "mcp_agent_id"
_MCP_ROLE = "mcp_role"
_MCP_AUTHENTICATED = "mcp_authenticated"

# --- Agent-session mapping (Phase 16.4 D.4) ---
# NOTE: Session mapping is now consolidated into MCPSessionMap
# (session_map.py), accessed via deps.get_session_map().
# The module-level dicts and functions below are DEPRECATED
# and kept only for backward compatibility during migration.
# They will be removed in a future version.

_agent_sessions: dict[str, str] = {}
_session_agents: dict[str, str] = {}


def register_agent_session(agent_id: str, session_id: str) -> None:
    """Map agent_id to MCP session_id for notification routing.
    
    DEPRECATED: Use MCPSessionMap.register() via deps.get_session_map().
    This function now delegates to MCPSessionMap as the single source of truth.
    """
    # Delegate to MCPSessionMap if available
    try:
        from .deps import get_session_map
        session_map = get_session_map()
        session_map.register(agent_id, session_id)
    except RuntimeError:
        # Fallback to legacy dicts if deps not initialized (testing)
        old_session = _agent_sessions.get(agent_id)
        if old_session and old_session != session_id:
            _session_agents.pop(old_session, None)
        _agent_sessions[agent_id] = session_id
        _session_agents[session_id] = agent_id


def unregister_agent_session(session_id: str) -> None:
    """Remove session mapping when MCP session closes.
    
    DEPRECATED: Use MCPSessionMap.unregister_session() via deps.get_session_map().
    """
    try:
        from .deps import get_session_map
        session_map = get_session_map()
        session_map.unregister_session(session_id)
    except RuntimeError:
        # Fallback to legacy dicts if deps not initialized (testing)
        agent_id = _session_agents.pop(session_id, None)
        if agent_id:
            _agent_sessions.pop(agent_id, None)


def get_session_id_for_agent(agent_id: str) -> Optional[str]:
    """Look up MCP session_id for an agent.
    
    DEPRECATED: Use MCPSessionMap.get_session_id() via deps.get_session_map().
    """
    try:
        from .deps import get_session_map
        session_map = get_session_map()
        return session_map.get_session_id(agent_id)
    except RuntimeError:
        return _agent_sessions.get(agent_id)


def get_agent_id_for_session(session_id: str) -> Optional[str]:
    """Look up agent_id for an MCP session.
    
    DEPRECATED: Use MCPSessionMap.get_agent_id() via deps.get_session_map().
    """
    try:
        from .deps import get_session_map
        session_map = get_session_map()
        return session_map.get_agent_id(session_id)
    except RuntimeError:
        return _session_agents.get(session_id)


# --- Token validation ---

def _extract_bearer_token(request: Request) -> str:
    """Extract Bearer token from Authorization header."""
    auth: str = request.headers.get("authorization", "")
    return auth.removeprefix("Bearer ").strip()


def _validate_token(
    token: str,
    token_mgr: Any,
    admin_token: str,
) -> tuple[str, Role] | None:
    """Validate a token and return (agent_id, role) or None."""
    # 1. Admin token
    if admin_token and token == admin_token:
        return ("admin", Role.ADMIN)

    # 2. JWT validation
    if token_mgr:
        try:
            payload = token_mgr.validate_token(token)
            return (payload.agent_id, Role(payload.role))
        except (ValueError, KeyError):
            pass

    # 3. Agent token (ag-*)
    if token.startswith("ag-"):
        return (token, Role.AGENT)

    return None


# --- Middleware ---

class MCPAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate MCP requests via Bearer token.

    Accepts optional constructor args (token_mgr, admin_token,
    storage) for testing. If not provided, resolves lazily
    from the deps module at request time.
    """

    def __init__(
        self,
        app: Any,
        token_mgr: Any = None,
        admin_token: str = "",
        storage: Any = None,
    ) -> None:
        super().__init__(app)
        self.token_mgr = token_mgr
        self.admin_token = admin_token
        self.storage = storage

    def _get_token_mgr(self) -> Any:
        """Resolve TokenManager: constructor arg or deps module."""
        if self.token_mgr is not None:
            return self.token_mgr
        from .deps import get_token_manager
        return get_token_manager()

    def _get_admin_token(self) -> str:
        """Resolve admin token: constructor arg or settings."""
        if self.admin_token:
            return self.admin_token
        from ..config import settings
        return settings.admin_token

    def _get_storage(self) -> Any:
        """Resolve Storage: constructor arg or deps module."""
        if self.storage is not None:
            return self.storage
        try:
            from .deps import get_storage
            return get_storage()
        except RuntimeError:
            return None

    async def dispatch(
        self, request: Request, call_next: Callable,
    ) -> Response:
        path = request.url.path

        # Whitelist: no auth required
        if path in MCP_AUTH_WHITELIST:
            return await call_next(request)

        # In "none" auth mode, skip validation but resolve identity
        from ..rbac_middleware import get_auth_mode
        mode = get_auth_mode()
        if mode == "none":
            await self._resolve_identity(request)
            return await call_next(request)

        token = _extract_bearer_token(request)
        if not token:
            return JSONResponse(
                {"error": "Missing Authorization header"},
                status_code=401,
            )

        token_mgr = self._get_token_mgr()
        admin_token = self._get_admin_token()

        result = _validate_token(token, token_mgr, admin_token)
        if result is None:
            return JSONResponse(
                {"error": "Invalid token"},
                status_code=401,
            )

        agent_id, role = result

        # For ag-* tokens, resolve real agent_id from Storage
        if agent_id.startswith("ag-"):
            storage = self._get_storage()
            if storage:
                agent = await storage.get_agent_by_token(agent_id)
                if agent:
                    agent_id = agent.get("agent_id", agent_id)

        setattr(request.state, _MCP_AGENT_ID, agent_id)
        setattr(request.state, _MCP_ROLE, role)
        setattr(request.state, _MCP_AUTHENTICATED, True)

        # Track session mapping from Mcp-Session-Id header
        mcp_sid = request.headers.get("mcp-session-id")
        if mcp_sid and agent_id != "admin":
            register_agent_session(agent_id, mcp_sid)

        logger.debug(
            "MCP auth: agent_id=%s role=%s path=%s",
            agent_id, role.value, path,
        )
        return await call_next(request)

    async def _resolve_identity(self, request: Request) -> None:
        """Best-effort identity resolution (none auth mode).

        In none-auth mode, we resolve agent_id via two paths:
        1. Bearer token (if present and valid) → set request.state
        2. MCP session ID header → look up session_map (registered
           during register_agent tool call)

        Path 2 is the primary mechanism for Hermes agents: they call
        register_agent first, which registers the MCP session → agent_id
        mapping. Subsequent tool calls carry the same mcp-session-id
        header, so we can resolve the agent_id without a valid token.
        """
        # Path 1: Try Bearer token resolution
        token = _extract_bearer_token(request)
        if token:
            token_mgr = self._get_token_mgr()
            admin_token = self._get_admin_token()
            result = _validate_token(token, token_mgr, admin_token)
            if result:
                agent_id, role = result
                if agent_id.startswith("ag-"):
                    storage = self._get_storage()
                    if storage:
                        agent = await storage.get_agent_by_token(agent_id)
                        if agent:
                            agent_id = agent.get("agent_id", agent_id)
                            setattr(request.state, _MCP_AGENT_ID, agent_id)
                            setattr(request.state, _MCP_ROLE, role)
                            return  # Token resolved successfully
                    # ag-* token not found in DB — don't use token as agent_id
                    # Fall through to Path 2 (session_map lookup)
                else:
                    setattr(request.state, _MCP_AGENT_ID, agent_id)
                    setattr(request.state, _MCP_ROLE, role)
                    return  # Token resolved successfully (admin or JWT)

        # Path 2: Try MCP session ID lookup (critical for none-auth mode)
        mcp_sid = request.headers.get("mcp-session-id")
        if mcp_sid:
            try:
                from .deps import get_session_map
                sm = get_session_map()
                agent_id = sm.get_agent_id(mcp_sid)
                if agent_id:
                    setattr(request.state, _MCP_AGENT_ID, agent_id)
                    from ..rbac import Role
                    setattr(request.state, _MCP_ROLE, Role.AGENT)
                    logger.debug(
                        "Resolved agent_id=%s from session=%s (none-auth)",
                        agent_id, mcp_sid[:12] + "..." if len(mcp_sid) > 12 else mcp_sid,
                    )
            except RuntimeError:
                pass  # session_map not initialized


# --- Helper functions for tool handlers ---

async def get_agent_id_from_state(
    request: Request, storage: Any,
) -> str | None:
    """Resolve the real agent_id from MCP auth state."""
    agent_id = getattr(request.state, _MCP_AGENT_ID, None)
    if agent_id is None:
        return None
    if agent_id.startswith("ag-"):
        agent = await storage.get_agent_by_token(agent_id)
        if agent:
            return agent.get("agent_id")
        return None
    return agent_id


def get_role_from_state(request: Request) -> Role | None:
    """Read the MCP-authenticated role from request state."""
    return getattr(request.state, _MCP_ROLE, None)


def is_authenticated(request: Request) -> bool:
    """Check if the MCP request was authenticated."""
    return getattr(request.state, _MCP_AUTHENTICATED, False)
