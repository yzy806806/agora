"""Webhook template rendering: pure Jinja2 substitution (Phase 14+ D.4).

Separated from execute_webhook for testability — no storage dependency.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from jinja2 import BaseLoader, Environment, TemplateError, Undefined

from .webhook_models import WebhookConfig, WebhookEvent

logger = logging.getLogger(__name__)


class _SilentUndefined(Undefined):
    """Return empty string for missing template variables."""

    def __str__(self) -> str:
        return ""

    def __repr__(self) -> str:
        return ""

    def __iter__(self):
        return iter([])

    def __bool__(self) -> bool:
        return False


_JINJA_ENV = Environment(
    loader=BaseLoader(),
    undefined=_SilentUndefined,
    keep_trailing_newline=True,
)


class WebhookRenderError(Exception):
    """Raised when template rendering fails."""


class WebhookPipelineError(Exception):
    """Raised when pipeline creation fails after rendering."""


def _build_context(
    webhook: WebhookConfig,
    event: WebhookEvent,
    timestamp: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build Jinja2 template context from webhook + event."""
    ts = timestamp or datetime.now(timezone.utc)
    return {
        "webhook": {
            "id": webhook.id,
            "project_id": webhook.project_id,
            "name": webhook.name,
        },
        "event": {
            "event_type": event.event,
            "payload": event.payload,
            "source_ip": event.source_ip,
            "headers": event.headers,
        },
        "timestamp": ts.isoformat(),
        "webhook_id": webhook.id,
    }


def render_template(
    template: dict | str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Render a pipeline_template dict using Jinja2 substitution.

    The template is serialized to JSON, then Jinja2 processes the
    string with the provided context, and the result is parsed back.
    """
    if isinstance(template, dict):
        template_str = json.dumps(template)
    else:
        template_str = template
    try:
        jinja_tmpl = _JINJA_ENV.from_string(template_str)
    except TemplateError as exc:
        raise WebhookRenderError(
            f"Invalid template syntax: {exc}"
        ) from exc
    try:
        rendered = jinja_tmpl.render(**context)
    except TemplateError as exc:
        raise WebhookRenderError(
            f"Template rendering failed: {exc}"
        ) from exc
    try:
        return json.loads(rendered)
    except json.JSONDecodeError as exc:
        raise WebhookRenderError(
            f"Rendered template is not valid JSON: {exc}"
        ) from exc
