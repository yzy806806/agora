"""Tests for TokenManager scope support — Phase 14+.E.6."""
import pytest
from agora.coordinator.token_manager import TokenManager, TokenPayload
from agora.coordinator.token_scopes import TokenScope


@pytest.fixture
def mgr() -> TokenManager:
    return TokenManager(secret="test-secret-key-1234567890")


class TestCreateTokenWithScopes:
    def test_default_scopes_by_role(self, mgr: TokenManager):
        token = mgr.create_token(agent_id="a1", role="admin")
        payload = mgr.validate_token(token)
        assert payload.scopes is not None
        assert "admin" in payload.scopes

    def test_explicit_scopes(self, mgr: TokenManager):
        token = mgr.create_token(
            agent_id="a1", role="agent",
            scopes=[TokenScope.REGISTER, TokenScope.CONNECT],
        )
        payload = mgr.validate_token(token)
        assert payload.scopes == ["register", "connect"]

    def test_string_scopes(self, mgr: TokenManager):
        token = mgr.create_token(
            agent_id="a1", role="agent",
            scopes=["register", "connect"],
        )
        payload = mgr.validate_token(token)
        assert payload.scopes == ["register", "connect"]

    def test_empty_scopes_list(self, mgr: TokenManager):
        token = mgr.create_token(
            agent_id="a1", role="agent", scopes=[],
        )
        payload = mgr.validate_token(token)
        assert payload.scopes == []


class TestValidateTokenScopes:
    def test_scopes_in_payload(self, mgr: TokenManager):
        token = mgr.create_token(
            agent_id="a1", role="agent",
            scopes=[TokenScope.ADMIN],
        )
        payload = mgr.validate_token(token)
        assert payload.scopes == ["admin"]

    def test_old_token_no_scope_claim(self, mgr: TokenManager):
        """Tokens created without scope claim return None for scopes."""
        import jwt as _jwt
        payload_data = {
            "agent_id": "old-agent", "role": "agent",
            "exp": 9999999999, "iat": 0, "jti": "old1",
        }
        token = _jwt.encode(payload_data, mgr._secret, algorithm="HS256")
        result = mgr.validate_token(token)
        assert result.scopes is None


class TestRotateTokenScopes:
    def test_rotate_preserves_scopes(self, mgr: TokenManager):
        token = mgr.create_token(
            agent_id="a1", role="agent",
            scopes=[TokenScope.REGISTER],
        )
        new_token = mgr.rotate_token(token)
        payload = mgr.validate_token(new_token)
        assert payload.scopes == ["register"]
