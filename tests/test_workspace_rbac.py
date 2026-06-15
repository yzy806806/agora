"""Tests for workspace RBAC permissions (Phase 14.6a).

Verifies WORKSPACE_READ/WRITE/ADMIN hierarchy and endpoint enforcement.
"""
from __future__ import annotations

import os

import pytest

from agora.coordinator.rbac import (
    Permission, Role, check_permission, _effective_permissions,
)


class TestPermissionHierarchy:
    """ADMIN > WRITE > READ implied permission expansion."""

    def test_admin_implies_write_and_read(self):
        eff = _effective_permissions({Permission.WORKSPACE_ADMIN})
        assert Permission.WORKSPACE_WRITE in eff
        assert Permission.WORKSPACE_READ in eff

    def test_write_implies_read(self):
        eff = _effective_permissions({Permission.WORKSPACE_WRITE})
        assert Permission.WORKSPACE_READ in eff
        assert Permission.WORKSPACE_ADMIN not in eff

    def test_read_implies_nothing_higher(self):
        eff = _effective_permissions({Permission.WORKSPACE_READ})
        assert Permission.WORKSPACE_WRITE not in eff
        assert Permission.WORKSPACE_ADMIN not in eff


class TestRolePermissions:
    """Role → workspace permission mapping via check_permission."""

    def test_admin_role_has_all_workspace_perms(self):
        for p in (Permission.WORKSPACE_READ, Permission.WORKSPACE_WRITE,
                  Permission.WORKSPACE_ADMIN):
            assert check_permission(Role.ADMIN, p)

    def test_agent_role_has_read_and_write(self):
        assert check_permission(Role.AGENT, Permission.WORKSPACE_READ)
        assert check_permission(Role.AGENT, Permission.WORKSPACE_WRITE)
        assert not check_permission(Role.AGENT, Permission.WORKSPACE_ADMIN)

    def test_observer_role_has_read_only(self):
        assert check_permission(Role.OBSERVER, Permission.WORKSPACE_READ)
        assert not check_permission(Role.OBSERVER, Permission.WORKSPACE_WRITE)
        assert not check_permission(Role.OBSERVER, Permission.WORKSPACE_ADMIN)
