"""RBAC Middleware for Agora Coordinator.

Phase 10.2a: FastAPI/ASGI middleware that extracts the caller's role
from each request and injects it for downstream @requires() checks.
Phase 14+.E.6: Also extracts token scopes for @requires_scope() checks.

Token resolution order:
1. JWT Bearer token → decode role + scope claims
2. Admin token fallback → Role.ADMIN, all scopes
3. No token → Role.OBSERVER (read-only), observer scopes

Only active when AGORA_RBAC_ENFORCE=true.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import Response

from .config import settings
from .rbac import Role, rbac_enforced
from .token_manager import TokenManager

logger = logging.getLogger(__name__)

# Header keys injected into request state
_STATE_ROLE = "_rbac_role"
_STATE_SCOPES = "_rbac_scopes"


def _resolve_role_and_scopes(
    request: Request,
) -> tuple[Role, list[str] | None]:
    """Determine role and scopes from the request's Authorization header."""
    auth: str = request.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip()

    if not token:
        return Role.OBSERVER, None

    # Admin token fallback: matches AGORA_ADMIN_TOKEN → ADMIN + all scopes
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
            # payload.scopes is None for old tokens → backward compat
            return role, payload.scopes
        except (ValueError, KeyError):
            pass

    # Agent tokens (ag-*) get AGENT role
    if token.startswith("ag-"):
        return Role.AGENT, None

    return Role.OBSERVER, None


class RBACMiddleware:
    """ASGI middleware that resolves and injects the caller's role."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(
        self, scope: dict[str, Any], receive: Callable, send: Callable,
    ) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if rbac_enforced():
            request = Request(scope, receive)
            role, scopes = _resolve_role_and_scopes(request)
            scope.setdefault("state", {})
            scope["state"][_STATE_ROLE] = role
            scope["state"][_STATE_SCOPES] = scopes
            logger.debug(
                "RBAC: resolved role=%s scopes=%s for %s",
                role.value, scopes, request.url.path,
            )

        await self.app(scope, receive, send)
