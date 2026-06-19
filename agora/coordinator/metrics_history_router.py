"""Metrics history REST API endpoint (Phase 13.3a).

GET /metrics/history?metric=agent_activity&range=7d&project_id=x
Returns Chart.js-compatible {metric, range, labels, datasets} JSON.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .metrics_history_models import (
    MetricType, MetricsHistoryResponse, RangePeriod,
)
from .rbac import Permission, Role, get_current_role, requires
from .storage import Storage

logger = logging.getLogger(__name__)

router = APIRouter()

_storage: Optional[Storage] = None


def init_metrics_history_deps(storage: Storage) -> None:
    """Wire storage dependency. Called from main.py on startup."""
    global _storage
    _storage = storage


def _get_storage() -> Storage:
    if _storage is None:
        raise HTTPException(status_code=503, detail="Not initialized")
    return _storage


# Map metric type to storage query function
_QUERY_MAP = {
    MetricType.agent_activity: "query_agent_activity",
    MetricType.task_throughput: "query_task_throughput",
    MetricType.discussion_outcomes: "query_discussion_outcomes",
    MetricType.pipeline_success_rate: "query_pipeline_success_rate",
    MetricType.rate_limit_usage: "query_rate_limit_usage",
}


@router.get("/metrics/history", response_model=MetricsHistoryResponse)
@requires(Permission.CONFIG_READ)
async def get_metrics_history(
    metric: MetricType,
    range: RangePeriod = RangePeriod.seven_days,
    project_id: Optional[str] = Query(default=None),
    _rbac_role: Role | None = Depends(get_current_role),
) -> MetricsHistoryResponse:
    """Return historical metrics data for dashboard charts."""
    storage = _get_storage()
    func_name = _QUERY_MAP[metric]
    result = await storage.query_metrics_history(
        func_name, range.value, project_id=project_id,
    )
    return MetricsHistoryResponse(
        metric=metric.value,
        range=range.value,
        labels=result.get("labels", []),
        datasets=result.get("datasets", []),
    )
