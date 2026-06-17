"""Tests for token_scopes module — Phase 14+.E.6."""
from agora.coordinator.token_scopes import (
    TokenScope, effective_scopes, has_scope,
    scopes_for_role, ROLE_DEFAULT_SCOPES,
)


class TestTokenScopeEnum:
    def test_all_scopes_defined(self):
        expected = [
            "register", "connect", "discuss", "execute_tasks",
            "workspace:read", "workspace:write", "workspace:manage",
            "webhooks:trigger", "webhooks:manage",
            "metrics:read", "admin",
        ]
        assert [s.value for s in TokenScope] == expected

    def test_str_enum(self):
        assert TokenScope.ADMIN == "admin"
        assert isinstance(TokenScope.REGISTER, str)


class TestEffectiveScopes:
    def test_admin_implies_all(self):
        eff = effective_scopes([TokenScope.ADMIN])
        assert eff == set(TokenScope)

    def test_manage_workspace_implies_write_read(self):
        eff = effective_scopes([TokenScope.MANAGE_WORKSPACE])
        assert TokenScope.WRITE_WORKSPACE in eff
        assert TokenScope.READ_WORKSPACE in eff

    def test_write_workspace_implies_read(self):
        eff = effective_scopes([TokenScope.WRITE_WORKSPACE])
        assert TokenScope.READ_WORKSPACE in eff
        assert TokenScope.WRITE_WORKSPACE not in effective_scopes(
            [TokenScope.READ_WORKSPACE])

    def test_manage_webhooks_implies_trigger(self):
        eff = effective_scopes([TokenScope.MANAGE_WEBHOOKS])
        assert TokenScope.TRIGGER_WEBHOOKS in eff

    def test_string_input(self):
        eff = effective_scopes(["admin"])
        assert TokenScope.ADMIN in eff

    def test_single_scope_no_implies(self):
        eff = effective_scopes([TokenScope.REGISTER])
        assert eff == {TokenScope.REGISTER}
