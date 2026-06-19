"""RBAC Middleware for Agora Coordinator.

Phase 10.2a: ASGI middleware that resolves caller role from requests.
Phase 14+.E.6: Also extracts token scopes for @requires_scope() checks.
Phase 15.B: Whitelist + three auth modes (none/token/rbac).

Token resolution order:
1. JWT Bearer token → decode role + scope claims
2. Admin token fallback → Role.ADMIN, all scopes
3. No token → Role.OBSERVER (read-only), observer scopes

Auth modes (AGORA_AUTH_MODE):
- none:  no authentication (dev, backward compat)
- token: Bearer token required, no RBAC permission check
- rbac:  Bearer token + RBAC permission check (production)
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import settings
from .rbac import Role
from .token_manager import TokenManager

logger = logging.getLogger(__name__)

# Header keys injected into request state
_STATE_ROLE = "_rbac_role"
_STATE_SCOPES = "_rbac_scopes"
_STATE_AUTHENTICATED = "_rbac_authenticated"

# Paths that never require authentication (even in rbac mode)
AUTH_WHITELIST: list[str] = [
    "/health",
    "/login",
    "/api/v1/health",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/discovery",
    "/api/v1/agents/register",
]


def _is_whitelisted(path: str) -> bool:
    """Check if a request path matches the auth whitelist."""
    if path in AUTH_WHITELIST:
        return True
    # Phase 15.C: registration status polling endpoint
    if path.startswith("/api/v1/agents/register/") and path.endswith("/status"):
        return True
    return False


def _extract_token(request: Request) -> str:
    """Extract auth token from Authorization header or dashboard_token cookie."""
    auth: str = request.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if token:
        return token
    # Fallback: dashboard_token cookie (set by /api/v1/auth/login)
    cookie_token = request.cookies.get("dashboard_token", "")
    return cookie_token.strip()


def _resolve_role_and_scopes(
    request: Request,
) -> tuple[Role, list[str] | None]:
    """Determine role and scopes from Authorization header or cookie."""
    token = _extract_token(request)

    if not token:
        return Role.OBSERVER, None

    # Admin token fallback
    admin_token = settings.admin_token
    if admin_token and token == admin_token:
        return Role.ADMIN, None  # None = all scopes

    # JWT decode → extract role + scope claims
    token_mgr: TokenManager | None = None
    try:
        token_mgr = getattr(request.app.state, "token_mgr", None)
    except (AttributeError, KeyError):
        pass
    if token_mgr:
        try:
            payload = token_mgr.validate_token(token)
            role = Role(payload.role)
            return role, payload.scopes
        except (ValueError, KeyError):
            pass

    # Agent tokens (ag-*) get AGENT role
    if token.startswith("ag-"):
        return Role.AGENT, None

    return Role.OBSERVER, None


def _is_token_valid(request: Request) -> bool:
    """Check if the request carries a valid token (any kind)."""
    token = _extract_token(request)
    if not token:
        return False

    # Admin token always valid
    admin_token = settings.admin_token
    if admin_token and token == admin_token:
        return True

    # Agent token (ag-*)
    if token.startswith("ag-"):
        return True

    # JWT validation
    token_mgr: TokenManager | None = None
    try:
        token_mgr = getattr(request.app.state, "token_mgr", None)
    except (AttributeError, KeyError):
        pass
    if token_mgr:
        try:
            token_mgr.validate_token(token)
            return True
        except (ValueError, KeyError):
            return False

    return False


def get_auth_mode() -> str:
    """Return effective auth mode, respecting legacy AGORA_RBAC_ENFORCE."""
    mode = settings.auth_mode
    if mode == "none" and settings.rbac_enforce:
        # Legacy compat: rbac_enforce=true maps to rbac mode
        return "rbac"
    return mode


class RBACMiddleware:
    """ASGI middleware: whitelist + auth mode (none/token/rbac)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(
        self, scope: dict[str, Any], receive: Callable, send: Callable,
    ) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        mode = get_auth_mode()

        if mode == "none":
            # No auth: still resolve role for downstream, but don't block
            if settings.rbac_enforce:
                # Legacy: resolve role for @requires() compat
                request = Request(scope, receive)
                role, scopes = _resolve_role_and_scopes(request)
                scope.setdefault("state", {})
                scope["state"][_STATE_ROLE] = role
                scope["state"][_STATE_SCOPES] = scopes
            await self.app(scope, receive, send)
            return

        # token or rbac mode: check whitelist + authentication
        request = Request(scope, receive)
        path = request.url.path

        if _is_whitelisted(path):
            await self.app(scope, receive, send)
            return

        # Authenticate: resolve role + scopes
        role, scopes = _resolve_role_and_scopes(request)
        authenticated = _is_token_valid(request)

        scope.setdefault("state", {})
        scope["state"][_STATE_ROLE] = role
        scope["state"][_STATE_SCOPES] = scopes
        scope["state"][_STATE_AUTHENTICATED] = authenticated

        if not authenticated:
            response = JSONResponse(
                {"detail": "Not authenticated"}, status_code=401,
            )
            await response(scope, receive, send)
            return

        # token mode: authenticated is enough, no RBAC check here
        # rbac mode: @requires() decorator handles permission checks
        if mode == "rbac":
            logger.debug(
                "RBAC: resolved role=%s scopes=%s for %s",
                role.value, scopes, path,
            )

        await self.app(scope, receive, send)
