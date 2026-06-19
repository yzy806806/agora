"""Tests for Phase 15 Part D: Task claim endpoint + event notification.

Phase 16.10: Updated — no more WS manager; uses event_bus.publish.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agora.coordinator.task_action_router import (
    TaskClaimRequest,
    init_task_action_deps,
    router,
)


def _make_task(task_id="t1", status="pending", assigned_to=None):
    """Create a mock task dict matching storage row shape."""
    return {
        "id": task_id, "graph_id": "g1", "motion_id": "m1",
        "title": "Test task", "description": "A test task",
        "status": status, "assigned_to": assigned_to,
        "required_capabilities": [], "depends_on": [],
        "artifact_paths": [], "error_message": None,
        "retry_count": 0, "created_at": "2026-01-01T00:00:00",
        "started_at": None, "completed_at": None,
    }


@pytest.fixture
def mock_storage():
    s = AsyncMock()
    s.get_task = AsyncMock(return_value=None)
    s.update_task_status = AsyncMock()
    return s


@pytest.fixture
def client(mock_storage):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    init_task_action_deps(mock_storage)
    return TestClient(app, raise_server_exceptions=False)


class TestClaimTask:
    def test_claim_pending_task(self, client, mock_storage):
        mock_storage.get_task = AsyncMock(side_effect=[
            _make_task(status="pending"),
            _make_task(status="assigned", assigned_to="dev-merger"),
        ])
        with patch(
            "agora.coordinator.event_bus.publish", new_callable=AsyncMock
        ):
            resp = client.post("/api/v1/tasks/t1/claim",
                               json={"agent_id": "dev-merger"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "assigned"
        assert data["assigned_to"] == "dev-merger"

    def test_claim_not_found(self, client, mock_storage):
        mock_storage.get_task = AsyncMock(return_value=None)
        resp = client.post("/api/v1/tasks/unknown/claim",
                           json={"agent_id": "dev-merger"})
        assert resp.status_code == 404

    def test_claim_wrong_status(self, client, mock_storage):
        mock_storage.get_task = AsyncMock(
            return_value=_make_task(status="running"))
        resp = client.post("/api/v1/tasks/t1/claim",
                           json={"agent_id": "dev-merger"})
        assert resp.status_code == 409

    def test_claim_already_assigned_other(self, client, mock_storage):
        mock_storage.get_task = AsyncMock(
            return_value=_make_task(status="assigned",
                                    assigned_to="other-agent"))
        resp = client.post("/api/v1/tasks/t1/claim",
                           json={"agent_id": "dev-merger"})
        assert resp.status_code == 409

    def test_claim_publishes_event(self, client, mock_storage):
        mock_storage.get_task = AsyncMock(side_effect=[
            _make_task(status="pending"),
            _make_task(status="assigned", assigned_to="dev-merger"),
        ])
        with patch(
            "agora.coordinator.event_bus.publish",
            new_callable=AsyncMock,
        ) as mock_publish:
            client.post("/api/v1/tasks/t1/claim",
                        json={"agent_id": "dev-merger"})
            mock_publish.assert_called_once()
            call_args = mock_publish.call_args
            assert call_args[0][0] == "TASK_ASSIGNED"
