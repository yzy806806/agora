"""Webhook data models: WebhookConfig, WebhookEvent, WebhookTriggerHistory."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class WebhookConfig(BaseModel):
    """Registered webhook endpoint configuration."""

    id: str
    project_id: str
    name: str
    description: str = ""
    secret_hash: str
    pipeline_template: dict  # JSON template for pipeline creation
    events: list[str] = Field(default_factory=lambda: ["push"])
    enabled: bool = True
    allowed_ips: list[str] = Field(default_factory=list)
    max_triggers_per_hour: int = 60
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )
    last_triggered_at: Optional[str] = None
    trigger_count: int = 0
    failure_count: int = 0


class WebhookEvent(BaseModel):
    """Incoming webhook payload (after verification)."""

    webhook_id: str
    event: str
    payload: dict
    headers: dict
    signature: str
    source_ip: str


class WebhookTriggerHistory(BaseModel):
    """Record of a webhook trigger attempt and its result."""

    id: int | None = None
    webhook_id: str
    event: str
    success: bool
    pipeline_id: Optional[str] = None
    error: Optional[str] = None
    source_ip: Optional[str] = None
    triggered_at: datetime = Field(default_factory=datetime.utcnow)


class WebhookRegisterRequest(BaseModel):
    """Request body for POST /api/v1/webhooks."""

    project_id: str
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    secret: str = Field(min_length=32)
    pipeline_template: str
    events: list[str] = Field(default_factory=lambda: ["push"])
    enabled: bool = True

    @field_validator("pipeline_template")
    @classmethod
    def validate_template_json(cls, v: str) -> str:
        import json
        json.loads(v)
        return v


class WebhookUpdateRequest(BaseModel):
    """Request body for PUT /api/v1/webhooks/{id}."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    secret: Optional[str] = Field(default=None, min_length=32)
    pipeline_template: Optional[str] = None
    events: Optional[list[str]] = None
    enabled: Optional[bool] = None

    @field_validator("pipeline_template")
    @classmethod
    def validate_template_json(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            import json
            json.loads(v)
        return v
