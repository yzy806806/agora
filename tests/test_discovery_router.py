"""Tests for discovery endpoint (simplified).

Removed: skill_category/min_proficiency filters, capabilities_v2.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from agora.coordinator.discovery_router import (
    init_discovery_deps,
    router,
    _agent_status,
    _build_discovered_agent,
)


@pytest.fixture
def mock_storage():
    s = AsyncMock()
    s.list_agents = AsyncMock(return_value=[])
    return s


@pytest.fixture
def client(mock_storage):
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    init_discovery_deps(mock_storage)
    return TestClient(app, raise_server_exceptions=False)


class TestDiscoveryEndpoint:
    def test_basic_discovery(self, client, mock_storage):
        resp = client.get("/api/v1/discovery")
        assert resp.status_code == 200
        data = resp.json()
        assert "protocol_versions" in data
        assert "1.0" in data["protocol_versions"]
        assert "2.0" in data["protocol_versions"]
        assert "features" in data
        assert "agents" in data
        assert data["api_version"] == "v1"

    def test_discovery_with_agents(self, client, mock_storage):
        mock_storage.list_agents = AsyncMock(return_value=[
            {
                "agent_id": "a1", "name": "DevBot",
                "model": "gpt-4", "is_approved": True,
                "is_online": True, "load": 0.3,
                "capabilities": ["python"],
            },
        ])
        resp = client.get("/api/v1/discovery")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["agents"]) == 1
        assert data["agents"][0]["agent_id"] == "a1"
        assert data["agents"][0]["status"] == "online"

    def test_filter_by_status(self, client, mock_storage):
        mock_storage.list_agents = AsyncMock(return_value=[
            {"agent_id": "a1", "name": "A1", "model": "",
             "is_approved": True, "is_online": True, "load": 0.0},
            {"agent_id": "a2", "name": "A2", "model": "",
             "is_approved": True, "is_online": False, "load": 0.0},
        ])
        resp = client.get("/api/v1/discovery?status=online")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["agents"]) == 1
        assert data["agents"][0]["agent_id"] == "a1"


class TestAgentStatusHelper:
    def test_offline_approved(self):
        assert _agent_status({
            "is_approved": True, "is_online": False, "load": 0.0
        }) == "offline"

    def test_online_approved(self):
        assert _agent_status({
            "is_approved": True, "is_online": True, "load": 0.3
        }) == "online"

    def test_busy_approved(self):
        assert _agent_status({
            "is_approved": True, "is_online": True, "load": 0.95
        }) == "busy"

    def test_pending_not_approved(self):
        assert _agent_status({
            "is_approved": False, "approval_status": "pending"
        }) == "pending"


class TestBuildDiscoveredAgent:
    def test_with_capabilities(self):
        agent = {
            "agent_id": "a1", "name": "Bot",
            "model": "gpt-4", "is_approved": True,
            "is_online": True, "load": 0.1,
            "capabilities": ["python", "review"],
        }
        result = _build_discovered_agent(agent)
        assert result.agent_id == "a1"
        assert result.status == "online"
        assert result.capabilities == ["python", "review"]
        assert result.skills == []

    def test_without_capabilities(self):
        agent = {
            "agent_id": "a2", "name": "Legacy",
            "model": "", "is_approved": True,
            "is_online": False, "load": 0.0,
        }
        result = _build_discovered_agent(agent)
        assert result.agent_id == "a2"
        assert result.status == "offline"
        assert result.capabilities == []
        assert result.skills == []
