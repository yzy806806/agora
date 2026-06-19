"""Tests for coordinator/router.py — HTTP REST API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agora.coordinator.models import MotionStatus, VotingMethod
from agora.coordinator.router import init_deps, router
from agora.coordinator.state import InvalidTransitionError, StateMachine


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
        "id": "m1", "title": "Test", "description": "Desc",
        "context": "", "rounds": 3,
        "voting_method": "simple_majority", "status": "draft",
        "current_round": 0, "decision": None, "rationale": None,
        "action_items": [], "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00", "closed_at": None,
    })
    s.get_motion = AsyncMock(return_value={
        "id": "m1", "title": "Test", "description": "Desc",
        "context": "", "rounds": 3,
        "voting_method": "simple_majority", "status": "draft",
        "current_round": 0, "decision": None, "rationale": None,
        "action_items": [], "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00", "closed_at": None,
    })
    s.list_motions = AsyncMock(return_value=[])
    s.get_messages = AsyncMock(return_value=[])
    s.get_votes = AsyncMock(return_value=[])
    s.get_vote_summary = AsyncMock(return_value={"counts": {"yes": 1, "no": 0}})
    return s


@pytest.fixture
def mock_sm():
    sm = AsyncMock(spec=StateMachine)
    sm.transition = AsyncMock(return_value=MotionStatus.DISCUSSING)
    return sm


@pytest.fixture
def client(mock_storage, mock_sm):
    """Create a FastAPI test client with mocked dependencies."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    init_deps(mock_storage, mock_sm)
    return TestClient(app, raise_server_exceptions=False)


class TestAgentAPI:
    def test_register_agent(self, client, mock_storage):
        resp = client.post("/agents/register", json={
            "agent_id": "a1", "name": "Test",
            "model": "gpt-4",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["agent_id"] == "a1"
        assert "agent_token" in data
        assert data["status"] in ("approved", "pending")

    def test_register_duplicate(self, client, mock_storage):
        mock_storage.get_agent = AsyncMock(return_value={"agent_id": "a1"})
        resp = client.post("/agents/register", json={
            "agent_id": "a1", "name": "Test",
        })
        assert resp.status_code == 409

    def test_deregister_agent(self, client, mock_storage):
        mock_storage.get_agent = AsyncMock(return_value={"agent_id": "a1"})
        resp = client.delete("/agents/a1")
        assert resp.status_code == 200

    def test_deregister_not_found(self, client, mock_storage):
        resp = client.delete("/agents/unknown")
        assert resp.status_code == 404

    def test_list_agents(self, client, mock_storage):
        resp = client.get("/agents")
        assert resp.status_code == 200


class TestMotionAPI:
    def test_create_motion(self, client, mock_storage):
        resp = client.post("/motions", json={
            "title": "Test", "description": "Desc",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "m1"

    def test_list_motions(self, client, mock_storage):
        resp = client.get("/motions")
        assert resp.status_code == 200

    def test_get_motion(self, client, mock_storage):
        resp = client.get("/motions/m1")
        assert resp.status_code == 200

    def test_get_motion_not_found(self, client, mock_storage):
        mock_storage.get_motion = AsyncMock(return_value=None)
        resp = client.get("/motions/unknown")
        assert resp.status_code == 404

    def test_start_motion(self, client, mock_storage, mock_sm):
        with patch("agora.coordinator.event_bus.publish", new_callable=AsyncMock):
            resp = client.post("/motions/m1/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

    def test_start_motion_invalid(self, client, mock_storage, mock_sm):
        mock_sm.transition = AsyncMock(
            side_effect=InvalidTransitionError("bad")
        )
        with patch("agora.coordinator.event_bus.publish", new_callable=AsyncMock):
            resp = client.post("/motions/m1/start")
        assert resp.status_code == 409


class TestHistoryResultAPI:
    def test_get_history(self, client, mock_storage):
        resp = client.get("/motions/m1/history")
        assert resp.status_code == 200

    def test_get_history_not_found(self, client, mock_storage):
        mock_storage.get_motion = AsyncMock(return_value=None)
        resp = client.get("/motions/unknown/history")
        assert resp.status_code == 404

    def test_get_result_not_closed(self, client, mock_storage):
        mock_storage.get_motion = AsyncMock(return_value={
            "id": "m1", "status": "discussing",
        })
        resp = client.get("/motions/m1/result")
        assert resp.status_code == 400

    def test_get_result_closed(self, client, mock_storage):
        mock_storage.get_motion = AsyncMock(return_value={
            "id": "m1", "status": "closed", "decision": "adopted",
            "rationale": "good", "action_items": [],
        })
        resp = client.get("/motions/m1/result")
        assert resp.status_code == 200
