"""Task CRUD operations — backend-agnostic."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect
from ..task_models import TaskNode

logger = logging.getLogger(__name__)


async def create_task_graph(
    db: Any, dialect: Dialect,
    graph_id: str, motion_id: str,
    parallel_mode: str = "auto",
    max_parallel_slots: int = 10,
    resource_conflict_policy: str = "warn",
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        """INSERT INTO task_graphs
        (id, motion_id, created_at, parallel_mode,
         max_parallel_slots, resource_conflict_policy)
        VALUES (?, ?, ?, ?, ?, ?)""",
        [graph_id, motion_id, now, parallel_mode,
         max_parallel_slots, resource_conflict_policy],
    )
    await db.execute(sql, params)
    await db.commit()
    return {
        "id": graph_id, "motion_id": motion_id,
        "created_at": now, "parallel_mode": parallel_mode,
        "max_parallel_slots": max_parallel_slots,
        "resource_conflict_policy": resource_conflict_policy,
    }


async def get_task_graph(db: Any, dialect: Dialect,
                         graph_id: str) -> Optional[dict]:
    sql, params = dialect.render(
        "SELECT * FROM task_graphs WHERE id = ?", [graph_id])
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    graph = dict(row)
    sql2, p2 = dialect.render(
        "SELECT * FROM tasks WHERE graph_id = ?", [graph_id])
    async with db.execute(sql2, p2) as cur:
        graph["tasks"] = [_decode_task(r) async for r in cur]
    return graph


async def list_task_graphs(
    db: Any, dialect: Dialect,
    limit: int = 100, offset: int = 0,
) -> list[dict]:
    sql, params = dialect.render(
        "SELECT * FROM task_graphs LIMIT ? OFFSET ?", [limit, offset])
    async with db.execute(sql, params) as cur:
        return [dict(r) async for r in cur]


async def get_task_graph_by_motion(
    db: Any, dialect: Dialect, motion_id: str,
) -> Optional[dict]:
    sql, params = dialect.render(
        "SELECT * FROM task_graphs WHERE motion_id = ?", [motion_id])
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return await get_task_graph(db, dialect, dict(row)["id"])


async def create_task(db: Any, dialect: Dialect,
                      task: TaskNode) -> dict:
    sql, params = dialect.render(
        """INSERT INTO tasks
        (id, graph_id, motion_id, title, description, status,
         assigned_to, required_capabilities, depends_on,
         artifact_paths, workspace_paths, error_message, created_at,
         started_at, completed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [task.id, task.graph_id, task.motion_id, task.title,
         task.description, task.status.value, task.assigned_to,
         json.dumps(task.required_capabilities),
         json.dumps(task.depends_on),
         json.dumps(task.artifact_paths),
         json.dumps(task.workspace_paths), task.error_message,
         task.created_at.isoformat(),
         task.started_at.isoformat() if task.started_at else None,
         task.completed_at.isoformat() if task.completed_at else None],
    )
    await db.execute(sql, params)
    await db.commit()
    return task.model_dump(mode="json")


async def get_task(db: Any, dialect: Dialect,
                   task_id: str) -> Optional[dict]:
    sql, params = dialect.render(
        "SELECT * FROM tasks WHERE id = ?", [task_id])
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return _decode_task(row) if row else None


async def list_tasks(
    db: Any, dialect: Dialect,
    graph_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100, offset: int = 0,
) -> list[dict]:
    conds, params = [], []
    if graph_id:
        conds.append("graph_id = ?"); params.append(graph_id)
    if agent_id:
        conds.append("assigned_to = ?"); params.append(agent_id)
    if status:
        conds.append("status = ?"); params.append(status)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    sql_base = f"SELECT * FROM tasks{where} LIMIT ? OFFSET ?"
    params += [limit, offset]
    sql, params = dialect.render(sql_base, params)
    async with db.execute(sql, params) as cur:
        return [_decode_task(r) async for r in cur]


async def update_task_status(
    db: Any, dialect: Dialect,
    task_id: str, status: str,
    assigned_to: Optional[str] = None,
    error_message: Optional[str] = None,
    artifact_paths: Optional[list[str]] = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    sets, params = ["status = ?"], [status]
    if assigned_to is not None:
        sets.append("assigned_to = ?"); params.append(assigned_to)
    if error_message is not None:
        sets.append("error_message = ?"); params.append(error_message)
    if artifact_paths is not None:
        sets.append("artifact_paths = ?")
        params.append(json.dumps(artifact_paths))
    if status == "running":
        sets.append("started_at = ?"); params.append(now)
    if status in ("done", "accepted", "rejected", "failed"):
        sets.append("completed_at = ?"); params.append(now)
    params.append(task_id)
    sql, params = dialect.render(
        f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", params)
    await db.execute(sql, params)
    await db.commit()


async def get_agent_task_count(
    db: Any, dialect: Dialect,
    agent_id: str, active_only: bool = True,
) -> int:
    if active_only:
        sql_base = """SELECT COUNT(*) FROM tasks
                 WHERE assigned_to = ? AND status IN ('assigned','running')"""
    else:
        sql_base = "SELECT COUNT(*) FROM tasks WHERE assigned_to = ?"
    sql, params = dialect.render(sql_base, [agent_id])
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return row[0] if row else 0


def _decode_task(row: Any) -> dict:
    d = dict(row)
    for key in ("required_capabilities", "depends_on",
                "artifact_paths", "workspace_paths"):
        val = d.get(key)
        if isinstance(val, str):
            d[key] = json.loads(val)
    return d


async def save_task_result(
    db: Any, dialect: Dialect,
    task_id: str, result_json: str,
) -> None:
    """Store structured TaskResult JSON in task_result column."""
    sql, params = dialect.render(
        "UPDATE tasks SET task_result = ? WHERE id = ?",
        [result_json, task_id],
    )
    await db.execute(sql, params)
    await db.commit()


async def get_task_result(
    db: Any, dialect: Dialect,
    task_id: str,
) -> Optional[dict]:
    """Retrieve structured TaskResult from task_result column."""
    sql, params = dialect.render(
        "SELECT task_result FROM tasks WHERE id = ?", [task_id],
    )
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    val = dict(row).get("task_result")
    if val is None:
        return None
    if isinstance(val, str):
        return json.loads(val)
    return val  # already a dict (JSONB from Postgres)
