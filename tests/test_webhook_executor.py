"""Tests for webhook_executor.py (simplified).

Template rendering removed; webhooks create pipelines from event data.
"""
import pytest

from agora.coordinator.webhook import WebhookConfig, WebhookEvent
from agora.coordinator.webhook import (
    WebhookPipelineError,
    execute_webhook,
)


def _webhook(**kw) -> WebhookConfig:
    d = dict(
        id="wh-1", project_id="proj-1", name="ci-hook",
        secret_hash="hash", pipeline_template={},
    )
    d.update(kw)
    return WebhookConfig(**d)


def _event(**kw) -> WebhookEvent:
    d = dict(
        webhook_id="wh-1", event="push",
        payload={"idea": "fix bug"},
        headers={}, signature="sig", source_ip="1.2.3.4",
    )
    d.update(kw)
    return WebhookEvent(**d)


class _FakeStorage:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.created = []

    async def create_pipeline_run(self, project_id, idea, **kw):
        if self.should_fail:
            raise RuntimeError("DB down")
        run = {"id": "pipe-1", "project_id": project_id, "idea": idea}
        self.created.append(run)
        return run


class TestExecuteWebhook:
    @pytest.mark.asyncio
    async def test_success(self):
        wh = _webhook()
        ev = _event()
        storage = _FakeStorage()
        result = await execute_webhook(wh, ev, storage)
        assert result["pipeline_id"] == "pipe-1"
        assert result["project_id"] == "proj-1"
        assert result["idea"] == "fix bug"
        assert result["metadata"]["webhook_id"] == "wh-1"
        assert result["metadata"]["source"] == "webhook"

    @pytest.mark.asyncio
    async def test_pipeline_creation_failure(self):
        wh = _webhook()
        ev = _event()
        storage = _FakeStorage(should_fail=True)
        with pytest.raises(WebhookPipelineError, match="DB down"):
            await execute_webhook(wh, ev, storage)

    @pytest.mark.asyncio
    async def test_default_idea(self):
        ev = _event(payload={"project_id": "proj-1"})
        wh = _webhook()
        storage = _FakeStorage()
        result = await execute_webhook(wh, ev, storage)
        assert result["idea"] == "Webhook-triggered pipeline"

    @pytest.mark.asyncio
    async def test_default_project_id(self):
        ev = _event(payload={"idea": "test"})
        wh = _webhook()
        storage = _FakeStorage()
        result = await execute_webhook(wh, ev, storage)
        assert result["project_id"] == "proj-1"
