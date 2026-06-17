"""Tests for webhook_models: WebhookConfig, WebhookEvent, WebhookTriggerHistory."""

import pytest

from agora.coordinator.webhook_models import (
    WebhookConfig,
    WebhookEvent,
    WebhookTriggerHistory,
)


class TestWebhookConfig:
    def test_defaults(self):
        cfg = WebhookConfig(
            id="wh-test", project_id="p1", name="test",
            secret_hash="abc", pipeline_template={"idea": "test"},
        )
        assert cfg.id  # auto-generated
        assert cfg.events == ["push"]
        assert cfg.enabled is True
        assert cfg.allowed_ips == []
        assert cfg.max_triggers_per_hour == 60
        assert cfg.trigger_count == 0
        assert cfg.failure_count == 0

    def test_custom_values(self):
        cfg = WebhookConfig(
            id="wh-1", project_id="p1", name="ci-hook",
            secret_hash="hash", pipeline_template={},
            events=["push", "pull_request"],
            allowed_ips=["10.0.0.0/8"],
            max_triggers_per_hour=120,
        )
        assert cfg.events == ["push", "pull_request"]
        assert cfg.allowed_ips == ["10.0.0.0/8"]
        assert cfg.max_triggers_per_hour == 120


class TestWebhookEvent:
    def test_create(self):
        ev = WebhookEvent(
            webhook_id="wh-1", event="push",
            payload={"ref": "main"}, headers={},
            signature="sha256=abc", source_ip="1.2.3.4",
        )
        assert ev.webhook_id == "wh-1"
        assert ev.event == "push"
        assert ev.source_ip == "1.2.3.4"


class TestWebhookTriggerHistory:
    def test_create(self):
        h = WebhookTriggerHistory(
            webhook_id="wh-1", event="push",
            success=True, pipeline_id="pipe-1",
        )
        assert h.success is True
        assert h.pipeline_id == "pipe-1"
        assert h.id is None
