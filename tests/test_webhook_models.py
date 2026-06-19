"""Tests for webhook_models (simplified).

Removed: allowed_ips, max_triggers_per_hour.
"""
import pytest

from agora.coordinator.webhook import (
    WebhookConfig,
    WebhookEvent,
    WebhookTriggerHistory,
)


class TestWebhookConfig:
    def test_defaults(self):
        cfg = WebhookConfig(
            id="wh-test", project_id="p1", name="test",
        )
        assert cfg.id == "wh-test"
        assert cfg.events == ["push"]
        assert cfg.enabled is True
        assert cfg.trigger_count == 0
        assert cfg.failure_count == 0

    def test_custom_values(self):
        cfg = WebhookConfig(
            id="wh-1", project_id="p1", name="ci-hook",
            secret_hash="hash",
            events=["push", "pull_request"],
        )
        assert cfg.events == ["push", "pull_request"]


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
