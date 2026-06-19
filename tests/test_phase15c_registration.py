"""Tests for Phase 15.C: Agent self-registration with approval flow.

Part 1: Storage layer + rate limiter + models.
"""
from __future__ import annotations

import pytest
import aiosqlite

from agora.coordinator.storage.agents import (
    register_agent,
    get_agent,
    get_agent_by_registration_token,
)
from agora.coordinator.storage.dialect import Dialect
from agora.coordinator.storage.schema import SCHEMA_SQL
from agora.coordinator.registration_rate_limiter import RegistrationRateLimiter
from agora.coordinator.models import (
    AgentRegistrationResponse,
    RegistrationStatusResponse,
    AgentStatus,
)


@pytest.fixture
async def db(tmp_path):
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA_SQL)
    yield conn
    await conn.close()


@pytest.fixture
def dialect() -> Dialect:
    return Dialect("sqlite")


@pytest.mark.asyncio
class TestRegistrationTokenStorage:
    async def test_register_with_registration_token(self, db, dialect):
        result = await register_agent(
            db, dialect, "r1", "RegAgent",
            agent_token="ag-test", approval_status="pending",
            registration_token="reg-abc123",
        )
        assert result["registration_token"] == "reg-abc123"

    async def test_get_by_registration_token(self, db, dialect):
        await register_agent(
            db, dialect, "r2", "RegAgent2",
            registration_token="reg-xyz789",
        )
        found = await get_agent_by_registration_token(
            db, dialect, "reg-xyz789")
        assert found is not None
        assert found["agent_id"] == "r2"

    async def test_get_by_token_not_found(self, db, dialect):
        found = await get_agent_by_registration_token(
            db, dialect, "nonexistent")
        assert found is None

    async def test_approval_preserves_reg_token(self, db, dialect):
        """set_agent_approval should NOT clear registration_token.

        Token is only cleared after agent retrieves agent_token
        via GET /agents/register/{id}/status (one-time read).
        """
        from agora.coordinator.storage.agents import set_agent_approval
        await register_agent(
            db, dialect, "r3", "RegAgent3",
            registration_token="reg-clear",
            approval_status="pending",
        )
        await set_agent_approval(db, dialect, "r3", True, "approved")
        agent = await get_agent(db, dialect, "r3")
        assert agent["approval_status"] == "approved"
        # registration_token MUST survive approval so agent can poll
        assert agent["registration_token"] == "reg-clear"

    async def test_clear_registration_token(self, db, dialect):
        """clear_registration_token removes token after one-time read."""
        from agora.coordinator.storage.agents import (
            set_agent_approval,
            clear_registration_token,
        )
        await register_agent(
            db, dialect, "r4", "RegAgent4",
            registration_token="reg-onetime",
            approval_status="pending",
        )
        await set_agent_approval(db, dialect, "r4", True, "approved")
        # Token still present after approval
        agent = await get_agent(db, dialect, "r4")
        assert agent["registration_token"] == "reg-onetime"
        # Now clear it (simulates agent retrieving agent_token)
        await clear_registration_token(db, dialect, "r4")
        agent = await get_agent(db, dialect, "r4")
        assert agent["registration_token"] == ""


class TestRegistrationRateLimiter:
    def test_allowed_under_limit(self):
        limiter = RegistrationRateLimiter(max_requests=3, window_seconds=60)
        assert limiter.is_allowed("1.2.3.4")
        assert limiter.is_allowed("1.2.3.4")
        assert limiter.is_allowed("1.2.3.4")

    def test_blocked_over_limit(self):
        limiter = RegistrationRateLimiter(max_requests=2, window_seconds=60)
        limiter.is_allowed("1.2.3.4")
        limiter.is_allowed("1.2.3.4")
        assert not limiter.is_allowed("1.2.3.4")

    def test_different_ips_independent(self):
        limiter = RegistrationRateLimiter(max_requests=1, window_seconds=60)
        assert limiter.is_allowed("1.1.1.1")
        assert limiter.is_allowed("2.2.2.2")
        assert not limiter.is_allowed("1.1.1.1")

    def test_reset(self):
        limiter = RegistrationRateLimiter(max_requests=1, window_seconds=60)
        limiter.is_allowed("1.1.1.1")
        limiter.reset("1.1.1.1")
        assert limiter.is_allowed("1.1.1.1")


class TestRegistrationModels:
    def test_registration_response_approval_required(self):
        resp = AgentRegistrationResponse(
            agent_id="a1", status=AgentStatus.PENDING,
            agent_token=None, registration_token="reg-abc",
            message="Pending", approval_required=True,
        )
        assert resp.agent_token is None
        assert resp.registration_token == "reg-abc"
        assert resp.approval_required is True

    def test_registration_response_auto_approved(self):
        resp = AgentRegistrationResponse(
            agent_id="a2", status=AgentStatus.APPROVED,
            agent_token="ag-xyz", message="OK",
        )
        assert resp.agent_token == "ag-xyz"
        assert resp.registration_token is None

    def test_status_response(self):
        resp = RegistrationStatusResponse(
            agent_id="a1", approval_status="pending",
            message="Pending approval.",
        )
        assert resp.agent_token is None

    def test_status_response_approved(self):
        resp = RegistrationStatusResponse(
            agent_id="a1", approval_status="approved",
            agent_token="ag-xyz", message="Approved.",
        )
        assert resp.agent_token == "ag-xyz"
