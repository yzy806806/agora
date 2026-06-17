"""Tests for Phase 10.2a: RBAC Models + Middleware."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from agora.coordinator.rbac import (
    Permission, Role, ROLE_PERMISSIONS,
    check_permission, rbac_enforced, requires,
)
from agora.coordinator.rbac_middleware import RBACMiddleware, _resolve_role_and_scopes


class TestRoleEnum:
    def test_role_values(self):
        assert Role.ADMIN.value == "admin"
        assert Role.AGENT.value == "agent"
        assert Role.OBSERVER.value == "observer"


class TestPermissionEnum:
    def test_permission_values(self):
        assert Permission.DISCUSSION_CREATE.value == "discussion:create"
        assert Permission.TASK_EXECUTE.value == "task:execute"
        assert Permission.ADMIN_FULL.value == "admin:full"


class TestRolePermissions:
    def test_admin_has_all(self):
        assert ROLE_PERMISSIONS[Role.ADMIN] == set(Permission)

    def test_agent_has_task_and_discussion(self):
        perms = ROLE_PERMISSIONS[Role.AGENT]
        assert Permission.DISCUSSION_CREATE in perms
        assert Permission.TASK_EXECUTE in perms
        assert Permission.AGENT_APPROVE not in perms
        assert Permission.ADMIN_FULL not in perms

    def test_observer_read_only(self):
        perms = ROLE_PERMISSIONS[Role.OBSERVER]
        assert Permission.CONFIG_READ in perms
        assert Permission.DISCUSSION_CREATE in perms
        assert Permission.TASK_EXECUTE not in perms
        assert Permission.ADMIN_FULL not in perms


class TestCheckPermission:
    def test_admin_allowed(self):
        assert check_permission(Role.ADMIN, Permission.ADMIN_FULL)

    def test_agent_denied_admin(self):
        assert not check_permission(Role.AGENT, Permission.ADMIN_FULL)

    def test_observer_denied_task(self):
        assert not check_permission(Role.OBSERVER, Permission.TASK_EXECUTE)
