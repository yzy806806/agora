"""Webhook executor: render_template + execute_webhook (Phase 14+ D.4).

Splits the orchestration (execute_webhook) from the pure rendering
(webhook_executor_render) for testability.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .webhook_models import WebhookConfig, WebhookEvent
from .webhook_executor_render import (
    WebhookPipelineError,
    WebhookRenderError,
    _build_context,
    render_template,
)

logger = logging.getLogger(__name__)


async def execute_webhook(
    webhook: WebhookConfig,
    event: WebhookEvent,
    storage: Any,
) -> dict[str, Any]:
    """Full trigger flow: render template -> create pipeline.

    Returns dict with pipeline_id and rendered template data.
    Raises WebhookRenderError or WebhookPipelineError on failure.
    """
    context = _build_context(webhook, event)
    # Render template
    try:
        rendered = render_template(webhook.pipeline_template, context)
    except WebhookRenderError:
        logger.error(
            "Template render failed for webhook %s", webhook.id,
        )
        raise
    # Extract idea and project_id from rendered template
    idea = rendered.get("idea", "Webhook-triggered pipeline")
    project_id = rendered.get(
        "project_id", webhook.project_id,
    )
    # Create pipeline via storage
    try:
        row = await storage.create_pipeline_run(
            project_id=project_id, idea=idea,
        )
    except Exception as exc:
        logger.error(
            "Pipeline creation failed for webhook %s: %s",
            webhook.id, exc,
        )
        raise WebhookPipelineError(
            f"Pipeline creation failed: {exc}"
        ) from exc
    # Log metadata about webhook source
    metadata = rendered.get("metadata", {})
    metadata["webhook_id"] = webhook.id
    metadata["source"] = "webhook"
    logger.info(
        "Webhook %s created pipeline %s for project %s",
        webhook.id, row.get("id"), project_id,
    )
    return {
        "pipeline_id": row.get("id"),
        "project_id": project_id,
        "idea": idea,
        "metadata": metadata,
    }
