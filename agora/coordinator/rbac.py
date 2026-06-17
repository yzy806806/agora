"""RBAC models and decorator for Agora Coordinator.

Phase 10.2a: Role/Permission enums, role-permission mapping,
and @requires(permission) decorator for FastAPI endpoints.
Phase 14+.E.6: Added @requires_scope() for scope-based access control.

AGORA_RBAC_ENFORCE env var controls enforcement:
- "true" / "1" → enforce RBAC checks
- unset / "false" → @requires is a no-op (backward compat)
"""
from __future__ import annotations

import functools
import logging
import os
from enum import Enum
from typing import Any, Callable, Sequence

from fastapi import Depends, HTTPException, Request

from .token_scopes import TokenScope, has_scope

logger = logging.getLogger(__name__)


class Role(str, Enum):
    """System roles with predefined permission sets."""
    ADMIN = "admin"
    AGENT = "agent"
    OBSERVER = "observer"


class Permission(str, Enum):
    """Granular permissions for RBAC."""
    DISCUSSION_CREATE = "discussion:create"
    DISCUSSION_VOTE = "discussion:vote"
    TASK_CREATE = "task:create"
    TASK_EXECUTE = "task:execute"
    TASK_REVIEW = "task:review"
    AGENT_REGISTER = "agent:register"
    AGENT_APPROVE = "agent:approve"
    CONFIG_READ = "config:read"
    CONFIG_WRITE = "config:write"
    ADMIN_FULL = "admin:full"
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_WRITE = "workspace:write"
    WORKSPACE_ADMIN = "workspace:admin"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: set(Permission),
    Role.AGENT: {
        Permission.DISCUSSION_CREATE, Permission.DISCUSSION_VOTE,
        Permission.TASK_CREATE, Permission.TASK_EXECUTE,
        Permission.TASK_REVIEW, Permission.AGENT_REGISTER,
        Permission.CONFIG_READ,
        Permission.WORKSPACE_READ, Permission.WORKSPACE_WRITE,
    },
    Role.OBSERVER: {
        Permission.DISCUSSION_CREATE, Permission.DISCUSSION_VOTE,
        Permission.CONFIG_READ,
        Permission.WORKSPACE_READ,
    },
}


def rbac_enforced() -> bool:
    """Check whether RBAC enforcement is enabled via env var."""
    return os.getenv("AGORA_RBAC_ENFORCE", "").lower() in ("true", "1")


# Permission hierarchy: higher implies lower.
_IMPLIED: dict[Permission, set[Permission]] = {
    Permission.WORKSPACE_ADMIN: {
        Permission.WORKSPACE_WRITE, Permission.WORKSPACE_READ,
    },
    Permission.WORKSPACE_WRITE: {Permission.WORKSPACE_READ},
}


def _effective_permissions(granted: set[Permission]) -> set[Permission]:
    """Expand granted permissions with their implied subordinates."""
    expanded = set(granted)
    for perm in granted:
        expanded |= _IMPLIED.get(perm, set())
    return expanded


def check_permission(role: Role, permission: Permission) -> bool:
    """Return True if role grants the given permission (with hierarchy)."""
    effective = _effective_permissions(ROLE_PERMISSIONS.get(role, set()))
    return permission in effective


def get_current_role(request: Request) -> Role | None:
    """FastAPI Depends that reads the RBAC role set by RBACMiddleware.

    The middleware writes to request.state._rbac_role; this dependency
    bridges it into endpoint kwargs so @requires can access it.
    """
    return getattr(request.state, "_rbac_role", None)


def requires(permission: Permission) -> Callable:
    """Decorator that checks the caller's role has the required permission.

    When AGORA_RBAC_ENFORCE is off (default), this is a no-op for
    backward compatibility.

    Endpoints using this MUST accept ``_rbac_role`` as a parameter
    with ``Depends(get_current_role)`` so the role from middleware
    is injected into kwargs.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not rbac_enforced():
                return await func(*args, **kwargs)
            role = kwargs.get("_rbac_role")
            if role is None:
                raise HTTPException(
                    status_code=401, detail="Not authenticated")
            if not check_permission(role, permission):
                raise HTTPException(
                    status_code=403, detail="Forbidden")
            return await func(*args, **kwargs)
        return wrapper
    return decorator


# --- Phase 14+.E.6: Scope-based access control ---

def get_current_scopes(request: Request) -> list[str] | None:
    """FastAPI Depends: read scopes from request state set by middleware.

    Returns None if no scopes were set (backward compat: all scopes).
    """
    return getattr(request.state, "_rbac_scopes", None)


def requires_scope(
    *required: TokenScope | str,
) -> Callable:
    """Decorator that checks the caller's token has the required scope(s).

    All *required* scopes must be present (with hierarchy expansion).
    When AGORA_RBAC_ENFORCE is off, this is a no-op.
    Tokens without a scope claim get all scopes (backward compat).

    Endpoints MUST accept ``_rbac_scopes`` with
    ``Depends(get_current_scopes)``.
    """
    req_scopes = [
        TokenScope(s) if isinstance(s, str) else s for s in required
    ]

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not rbac_enforced():
                return await func(*args, **kwargs)
            token_scopes: list[str] | None = kwargs.get("_rbac_scopes")
            # No scope claim → backward compat: all scopes granted
            if token_scopes is None:
                return await func(*args, **kwargs)
            for req in req_scopes:
                if not has_scope(token_scopes, req):
                    raise HTTPException(
                        status_code=403,
                        detail=f"Missing scope: {req.value}",
                    )
            return await func(*args, **kwargs)
        return wrapper
    return decorator
