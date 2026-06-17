"""Token scopes for Protocol v2 — fine-grained access control.

Each scope represents a category of operations an agent token authorizes.
Scopes are embedded in JWT as a ``scope`` claim (list of strings).
Tokens without a scope claim receive ALL scopes (backward compat).
"""
from __future__ import annotations

from enum import Enum
from typing import Sequence


class TokenScope(str, Enum):
    """What an agent token authorizes."""

    REGISTER = "register"
    CONNECT = "connect"
    DISCUSS = "discuss"
    EXECUTE_TASKS = "execute_tasks"
    READ_WORKSPACE = "workspace:read"
    WRITE_WORKSPACE = "workspace:write"
    MANAGE_WORKSPACE = "workspace:manage"
    TRIGGER_WEBHOOKS = "webhooks:trigger"
    MANAGE_WEBHOOKS = "webhooks:manage"
    VIEW_METRICS = "metrics:read"
    ADMIN = "admin"


# Scope hierarchy: higher scopes imply lower ones
_SCOPE_IMPLIES: dict[TokenScope, set[TokenScope]] = {
    TokenScope.ADMIN: set(TokenScope),
    TokenScope.MANAGE_WORKSPACE: {
        TokenScope.WRITE_WORKSPACE, TokenScope.READ_WORKSPACE,
    },
    TokenScope.WRITE_WORKSPACE: {TokenScope.READ_WORKSPACE},
    TokenScope.MANAGE_WEBHOOKS: {
        TokenScope.TRIGGER_WEBHOOKS,
    },
}


def effective_scopes(granted: Sequence[TokenScope | str]) -> set[TokenScope]:
    """Expand granted scopes with their implied subordinates."""
    expanded: set[TokenScope] = set()
    for s in granted:
        scope = TokenScope(s) if isinstance(s, str) else s
        expanded.add(scope)
        expanded |= _SCOPE_IMPLIES.get(scope, set())
    return expanded


def has_scope(
    granted: Sequence[TokenScope | str],
    required: TokenScope | str,
) -> bool:
    """Check whether *granted* scopes cover *required*."""
    req = TokenScope(required) if isinstance(required, str) else required
    return req in effective_scopes(granted)


# Default scopes per role (for tokens created without explicit scopes)
ROLE_DEFAULT_SCOPES: dict[str, list[TokenScope]] = {
    "admin": list(TokenScope),
    "agent": [
        TokenScope.REGISTER, TokenScope.CONNECT,
        TokenScope.DISCUSS, TokenScope.EXECUTE_TASKS,
        TokenScope.READ_WORKSPACE, TokenScope.WRITE_WORKSPACE,
        TokenScope.VIEW_METRICS,
    ],
    "observer": [
        TokenScope.CONNECT, TokenScope.DISCUSS,
        TokenScope.READ_WORKSPACE, TokenScope.VIEW_METRICS,
    ],
}


def scopes_for_role(role: str) -> list[TokenScope]:
    """Return default scopes for a given role."""
    return ROLE_DEFAULT_SCOPES.get(role, ROLE_DEFAULT_SCOPES["observer"])
