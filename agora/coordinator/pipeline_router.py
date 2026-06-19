"""Phase 13.1e: Pipeline REST API routes."""
from __future__ import annotations
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from .pipeline_models import PipelinePhase, PipelineStartRequest
from .pipeline_retry import is_retryable
from .rbac import Permission, Role, get_current_role, requires
from .storage import Storage

logger = logging.getLogger(__name__)
router = APIRouter()
_storage: Optional[Storage] = None

def init_pipeline_router_deps(storage: Storage) -> None:
    global _storage; _storage = storage

def _s() -> Storage:
    if _storage is None: raise HTTPException(503, detail="Not initialized")
    return _storage

async def _get(pid: str) -> dict:
    r = await _s().get_pipeline_run(pid)
    if r is None: raise HTTPException(404, detail="Pipeline not found")
    return r

@router.post("/pipelines")
@requires(Permission.TASK_CREATE)
async def start_pipeline(
    body: PipelineStartRequest,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    row = await _s().create_pipeline_run(
        project_id=body.project_id, idea=body.idea)
    logger.info("Pipeline %s started for project %s", row["id"], body.project_id)
    return row

@router.get("/pipelines/{pipeline_id}")
@requires(Permission.CONFIG_READ)
async def get_pipeline(
    pipeline_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    return await _get(pipeline_id)

@router.get("/pipelines")
@requires(Permission.CONFIG_READ)
async def list_pipelines(
    project_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    items = await _s().list_pipeline_runs(
        project_id=project_id, limit=limit, offset=offset)
    total = await _s().count_pipeline_runs(project_id=project_id)
    return {"pipelines": items, "count": total}

@router.post("/pipelines/{pipeline_id}/cancel")
@requires(Permission.TASK_EXECUTE)
async def cancel_pipeline(
    pipeline_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    row = await _get(pipeline_id)
    if row["phase"] in (PipelinePhase.COMPLETED.value, PipelinePhase.FAILED.value):
        raise HTTPException(400, detail="Pipeline already terminal")
    u = await _s().update_pipeline_run(pipeline_id, {
        "phase": PipelinePhase.FAILED.value,
        "failed_phase": row["phase"],
        "error": "Cancelled by user",
    })
    if u is None: raise HTTPException(404, detail="Pipeline not found")
    return u

@router.post("/pipelines/{pipeline_id}/retry")
@requires(Permission.TASK_EXECUTE)
async def retry_pipeline(
    pipeline_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    row = await _get(pipeline_id)
    if row["phase"] != PipelinePhase.FAILED.value:
        raise HTTPException(400, detail="Only failed pipelines can be retried")
    fp = row.get("failed_phase")
    if fp and not is_retryable(PipelinePhase(fp)):
        raise HTTPException(400, detail="Pipeline failure is not retryable")
    u = await _s().update_pipeline_run(pipeline_id, {
        "phase": PipelinePhase.DISCUSSING.value,
        "error": None, "failed_phase": None,
    })
    if u is None: raise HTTPException(404, detail="Pipeline not found")
    return u
