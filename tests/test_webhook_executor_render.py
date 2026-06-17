"""Tests for webhook template rendering (webhook_executor_render.py)."""
import json
import pytest

from agora.coordinator.webhook_models import WebhookConfig, WebhookEvent
from agora.coordinator.webhook_executor_render import (
    WebhookRenderError,
    _build_context,
    render_template,
)


def _make_webhook(**overrides) -> WebhookConfig:
    defaults = dict(
        id="wh-1", project_id="proj-1", name="test-hook",
        secret_hash="abc123",
        pipeline_template={"idea": "test", "project_id": "proj-1"},
    )
    defaults.update(overrides)
    return WebhookConfig(**defaults)


def _make_event(**overrides) -> WebhookEvent:
    defaults = dict(
        webhook_id="wh-1", event="push",
        payload={"ref": "refs/heads/main"},
        headers={}, signature="sig", source_ip="1.2.3.4",
    )
    defaults.update(overrides)
    return WebhookEvent(**defaults)


class TestBuildContext:
    def test_basic_fields(self):
        wh = _make_webhook()
        ev = _make_event()
        ctx = _build_context(wh, ev)
        assert ctx["webhook"]["id"] == "wh-1"
        assert ctx["webhook"]["project_id"] == "proj-1"
        assert ctx["webhook"]["name"] == "test-hook"
        assert ctx["event"]["event_type"] == "push"
        assert ctx["event"]["payload"]["ref"] == "refs/heads/main"
        assert ctx["webhook_id"] == "wh-1"
        assert "timestamp" in ctx

    def test_custom_timestamp(self):
        from datetime import datetime, timezone
        ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        ctx = _build_context(_make_webhook(), _make_event(), ts)
        assert ctx["timestamp"] == ts.isoformat()


class TestRenderTemplate:
    def test_simple_substitution(self):
        tmpl = {"idea": "{{ event.event_type }} from {{ webhook.name }}"}
        ctx = {"event": {"event_type": "push"}, "webhook": {"name": "ci"}}
        result = render_template(tmpl, ctx)
        assert result["idea"] == "push from ci"

    def test_nested_payload_access(self):
        tmpl = {"idea": "{{ event.payload.message }}"}
        ctx = {"event": {"payload": {"message": "hello"}, "event_type": "push"}}
        result = render_template(tmpl, ctx)
        assert result["idea"] == "hello"

    def test_missing_variable_silent(self):
        tmpl = {"idea": "{{ missing_var }}fallback"}
        ctx = {}
        result = render_template(tmpl, ctx)
        assert result["idea"] == "fallback"

    def test_string_template_input(self):
        tmpl_str = '{"idea": "test"}'
        result = render_template(tmpl_str, {})
        assert result["idea"] == "test"

    def test_invalid_template_syntax(self):
        tmpl = {"idea": "{{ unclosed"}
        with pytest.raises(WebhookRenderError, match="Invalid template"):
            render_template(tmpl, {})

    def test_rendered_not_json(self):
        # Template produces non-JSON output
        tmpl_str = "not valid json {{ x }}"
        with pytest.raises(WebhookRenderError, match="not valid JSON"):
            render_template(tmpl_str, {"x": "val"})

    def test_complex_template(self):
        tmpl = {
            "idea": "{{ event.payload.msg | default('default') }}",
            "project_id": "{{ webhook.project_id }}",
            "metadata": {
                "webhook_id": "{{ webhook.id }}",
                "event": "{{ event.event_type }}",
            },
        }
        ctx = {
            "webhook": {"id": "wh-1", "project_id": "proj-1", "name": "hook"},
            "event": {"event_type": "push", "payload": {"msg": "commit msg"}},
        }
        result = render_template(tmpl, ctx)
        assert result["idea"] == "commit msg"
        assert result["project_id"] == "proj-1"
        assert result["metadata"]["webhook_id"] == "wh-1"
