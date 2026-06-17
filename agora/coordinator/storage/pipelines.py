"""PipelineRun CRUD — backend-agnostic."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect

logger = logging.getLogger(__name__)


async def create_pipeline_run(
    db: Any, dialect: Dialect,
    project_id: str, idea: str, phase: str = "discussing",
    motion_id: str | None = None, graph_id: str | None = None,
) -> dict:
    run_id = uuid.uuid4().hex[:16]
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": run_id, "project_id": project_id, "idea": idea,
        "motion_id": motion_id, "graph_id": graph_id,
        "phase": phase, "started_at": now,
        "completed_at": None, "tasks_total": 0,
        "tasks_completed": 0, "tasks_failed": 0,
        "review_outcome": None, "release_version": None,
        "error": None, "failed_phase": None,
    }
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["?"] * len(row))
    sql, params = dialect.render(
        f"INSERT INTO pipeline_runs ({cols}) "
        f"VALUES ({placeholders})", list(row.values()))
    await db.execute(sql, params)
    await db.commit()
    return dict(row)


async def get_pipeline_run(
    db: Any, dialect: Dialect, run_id: str,
) -> Optional[dict]:
    sql, params = dialect.render(
        "SELECT * FROM pipeline_runs WHERE id = ?", [run_id])
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_pipeline_runs(
    db: Any, dialect: Dialect,
    project_id: str | None = None, phase: str | None = None,
    limit: int = 100, offset: int = 0,
) -> list[dict]:
    clauses, params = [], []
    if project_id is not None:
        clauses.append("project_id = ?"); params.append(project_id)
    if phase is not None:
        clauses.append("phase = ?"); params.append(phase)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])
    sql, params = dialect.render(
        f"SELECT * FROM pipeline_runs {where} "
        "ORDER BY started_at DESC LIMIT ? OFFSET ?", params)
    async with db.execute(sql, params) as cur:
        rows = [dict(r) async for r in cur]
    return rows


async def update_pipeline_run(
    db: Any, dialect: Dialect,
    run_id: str, updates: dict,
) -> Optional[dict]:
    allowed = {
        "phase", "motion_id", "graph_id", "completed_at",
        "tasks_total", "tasks_completed", "tasks_failed",
        "review_outcome", "release_version", "error",
        "failed_phase",
    }
    sets, params = [], []
    for k, v in updates.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?"); params.append(v)
    if not sets:
        return await get_pipeline_run(db, dialect, run_id)
    params.append(run_id)
    sql, params = dialect.render(
        f"UPDATE pipeline_runs SET {', '.join(sets)} "
        "WHERE id = ?", params)
    await db.execute(sql, params)
    await db.commit()
    return await get_pipeline_run(db, dialect, run_id)


async def delete_pipeline_run(
    db: Any, dialect: Dialect, run_id: str,
) -> bool:
    sql, params = dialect.render(
        "DELETE FROM pipeline_runs WHERE id = ?", [run_id])
    cursor = await db.execute(sql, params)
    await db.commit()
    return cursor.rowcount > 0


async def count_pipeline_runs(
    db: Any, dialect: Dialect,
    project_id: str | None = None, phase: str | None = None,
) -> int:
    clauses, params = [], []
    if project_id is not None:
        clauses.append("project_id = ?"); params.append(project_id)
    if phase is not None:
        clauses.append("phase = ?"); params.append(phase)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql, params = dialect.render(
        f"SELECT COUNT(*) FROM pipeline_runs {where}", params)
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return row[0] if row else 0
