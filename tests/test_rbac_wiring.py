"""Tests for Phase 10.2d: Endpoint Permission Wiring."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agora.coordinator.models import MotionStatus
from agora.coordinator.rbac import Permission
from agora.coordinator.router import init_deps, router
from agora.coordinator.state import StateMachine


@pytest.fixture
def mock_storage():
    s = AsyncMock()
    s.get_agent = AsyncMock(return_value=None)
    s.register_agent = AsyncMock(return_value={
        "agent_id": "a1", "name": "Test", "model": "gpt-4",
        "hermes_endpoint": "http://localhost", "capabilities": [],
        "role": "participant", "registered_at": "2026-01-01T00:00:00",
        "is_online": False, "last_seen": None,
    })
    s.list_agents = AsyncMock(return_value=[])
    s.deregister_agent = AsyncMock()
    s.create_motion = AsyncMock(return_value={
        "id": "m1", "title": "T", "description": "D",
        "context": "", "rounds": 3,
        "voting_method": "simple_majority", "status": "draft",
        "current_round": 0, "decision": None, "rationale": None,
        "action_items": [], "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00", "closed_at": None,
    })
    s.get_motion = AsyncMock(return_value={
        "id": "m1", "title": "T", "description": "D",
        "context": "", "rounds": 3,
        "voting_method": "simple_majority", "status": "draft",
        "current_round": 0, "decision": None, "rationale": None,
        "action_items": [], "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00", "closed_at": None,
    })
    s.list_motions = AsyncMock(return_value=[])
    s.get_messages = AsyncMock(return_value=[])
    s.get_votes = AsyncMock(return_value=[])
    s.get_vote_summary = AsyncMock(return_value={"counts": {}})
    s.set_agent_approval = AsyncMock()
    return s


@pytest.fixture
def mock_sm():
    sm = AsyncMock(spec=StateMachine)
    sm.transition = AsyncMock(return_value=MotionStatus.DISCUSSING)
    return sm


@pytest.fixture
def client(mock_storage, mock_sm):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    init_deps(mock_storage, mock_sm)
    return TestClient(app, raise_server_exceptions=False)


class TestRbacOffBackwardCompat:
    """When AGORA_RBAC_ENFORCE is off, @requires is a no-op."""

    def test_register_agent_works(self, client, mock_storage):
        resp = client.post("/agents/register", json={
            "agent_id": "a1", "name": "Test", "model": "gpt-4",
        })
        assert resp.status_code == 201

    def test_create_motion_works(self, client, mock_storage):
        resp = client.post("/motions", json={
            "title": "Test", "description": "Desc",
        })
        assert resp.status_code == 200

    def test_public_endpoints_no_auth(self, client):
        """In none mode (default), all endpoints work without auth."""
        assert client.get("/agents").status_code == 200
        assert client.get("/motions").status_code == 200


class TestRbacOnEnforcement:
    """When AGORA_RBAC_ENFORCE=1, @requires checks permissions."""

    def test_register_agent_whitelisted(self, client, mock_storage):
        """Phase 15.B/C: /agents/register is whitelisted from auth.

        Even in rbac mode, new agents can register without a token.
        """
        with patch.dict(os.environ, {"AGORA_RBAC_ENFORCE": "1"}):
            from agora.coordinator.rbac import rbac_enforced
            assert rbac_enforced()
            # Whitelisted: no auth needed for registration
            resp = client.post("/agents/register", json={
                "agent_id": "a1", "name": "Test", "model": "gpt-4",
            })
            assert resp.status_code == 201

    def test_create_motion_needs_role(self, client, mock_storage):
        with patch.dict(os.environ, {"AGORA_RBAC_ENFORCE": "1"}):
            resp = client.post("/motions", json={
                "title": "Test", "description": "Desc",
            })
            assert resp.status_code == 401


class TestDecoratorsPresent:
    """Verify @requires decorators are wired on key endpoints."""

    def test_register_agent_no_decorator(self):
        """Phase 15.B/C: /agents/register is whitelisted, no @requires."""
        from agora.coordinator.router import register_agent
        # Whitelisted endpoint: no @requires decorator
        assert not hasattr(register_agent, "__wrapped__")

    def test_create_motion_has_decorator(self):
        from agora.coordinator.router import create_motion
        assert hasattr(create_motion, "__wrapped__")

    def test_deregister_agent_has_decorator(self):
        from agora.coordinator.router import deregister_agent
        assert hasattr(deregister_agent, "__wrapped__")

    def test_admin_approve_has_decorator(self):
        from agora.coordinator.router import admin_approve_agent
        assert hasattr(admin_approve_agent, "__wrapped__")


class TestWsRbacCheck:
    """Verify RBAC permission checks work for agent registration."""

    def test_observer_cannot_register_agent(self):
        """Observer role lacks AGENT_REGISTER, should be rejected."""
        from agora.coordinator.rbac import check_permission, Role, Permission
        assert not check_permission(Role.OBSERVER, Permission.AGENT_REGISTER)
