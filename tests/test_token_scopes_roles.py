"""Tests for has_scope + scopes_for_role — Phase 14+.E.6."""
from agora.coordinator.token_scopes import (
    TokenScope, has_scope, scopes_for_role, ROLE_DEFAULT_SCOPES,
)


class TestHasScope:
    def test_direct_match(self):
        assert has_scope([TokenScope.REGISTER], TokenScope.REGISTER)

    def test_hierarchy_match(self):
        assert has_scope(
            [TokenScope.MANAGE_WORKSPACE], TokenScope.READ_WORKSPACE)

    def test_no_match(self):
        assert not has_scope(
            [TokenScope.REGISTER], TokenScope.ADMIN)

    def test_string_inputs(self):
        assert has_scope(["admin"], "workspace:read")

    def test_empty_granted(self):
        assert not has_scope([], TokenScope.REGISTER)

    def test_admin_covers_all(self):
        for scope in TokenScope:
            assert has_scope([TokenScope.ADMIN], scope)


class TestScopesForRole:
    def test_admin_gets_all(self):
        scopes = scopes_for_role("admin")
        assert set(scopes) == set(TokenScope)

    def test_agent_gets_standard(self):
        scopes = scopes_for_role("agent")
        assert TokenScope.REGISTER in scopes
        assert TokenScope.CONNECT in scopes
        assert TokenScope.ADMIN not in scopes

    def test_observer_limited(self):
        scopes = scopes_for_role("observer")
        assert TokenScope.CONNECT in scopes
        assert TokenScope.READ_WORKSPACE in scopes
        assert TokenScope.WRITE_WORKSPACE not in scopes

    def test_unknown_role_gets_observer(self):
        scopes = scopes_for_role("unknown")
        assert scopes == ROLE_DEFAULT_SCOPES["observer"]
