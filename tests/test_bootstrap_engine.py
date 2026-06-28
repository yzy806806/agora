"""Tests for BootstrapEngine module."""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agora.coordinator.bootstrap import BootstrapConfig, BootstrapEngine
from agora.coordinator.bootstrap.approval_flow import ApprovalFlow
from agora.coordinator.bootstrap.discussion_driver import DiscussionResult
from agora.coordinator.bootstrap.trigger_manager import TriggerManager
from agora.coordinator.storage.schema import SCHEMA_SQL


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(loop_scope="module")
async def db_path(tmp_path_factory):
    import aiosqlite
    path = str(tmp_path_factory.mktemp("engine") / "test.db")
    async with aiosqlite.connect(path) as conn:
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()
    yield path


@pytest_asyncio.fixture(loop_scope="module")
async def engine(db_path):
    cfg = BootstrapConfig(
        db_path=db_path,
        coordinator_url="http://localhost:8765",
    )
    eng = BootstrapEngine(cfg)
    eng.init_routes()
    return eng


class TestBootstrapConfig:
    def test_defaults(self):
        cfg = BootstrapConfig(db_path="/tmp/test.db")
        assert cfg.coordinator_url == "http://localhost:8765"


class TestBootstrapEngine:
    @pytest.mark.asyncio
    async def test_init_routes(self, engine):
        from agora.coordinator.bootstrap import routes as r
        assert r._trigger_mgr is not None
        assert r._approval_flow is not None
        assert r._db_path is not None

    @pytest.mark.asyncio
    async def test_process_triggers_empty(self, engine):
        motion_ids = await engine.process_triggers()
        assert motion_ids == []

    @pytest.mark.asyncio
    async def test_process_approval_approved(self, engine):
        aid = await engine.approval_flow.submit_for_approval(
            motion_id="m_test", decision="adopted",
            action_items=[{"title": "Build X", "category": "development"}],
        )
        # Mock task generation to avoid real HTTP calls
        mock_resp = AsyncMock()
        mock_resp.status = 201
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={"id": "t_mock"})

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("agora.coordinator.bootstrap.task_generator.aiohttp.ClientSession",
                    return_value=mock_session):
            result = await engine.process_approval(
                aid, approved=True, approved_by="alice",
            )
        assert result["status"] == "approved"
        assert "tasks_created" in result

    @pytest.mark.asyncio
    async def test_process_approval_rejected(self, engine):
        aid = await engine.approval_flow.submit_for_approval(
            motion_id="m_rej", decision="no_consensus",
        )
        result = await engine.process_approval(
            aid, approved=False, feedback="Redo",
        )
        assert result["status"] == "rejected"
        assert "tasks_created" not in result

    @pytest.mark.asyncio
    async def test_check_schedules_empty(self, engine):
        ids = await engine.check_schedules()
        assert ids == []
