"""Task CRUD operations for the Agora Coordinator storage layer."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from ..task_models import TaskNode

logger = logging.getLogger(__name__)


async def create_task_graph(
    db: aiosqlite.Connection, graph_id: str, motion_id: str,
    parallel_mode: str = "auto",
    max_parallel_slots: int = 10,
    resource_conflict_policy: str = "warn",
) -> dict:
    """Insert a new TaskGraph row."""
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """INSERT INTO task_graphs
        (id, motion_id, created_at, parallel_mode,
         max_parallel_slots, resource_conflict_policy)
        VALUES (?, ?, ?, ?, ?, ?)""",
        [graph_id, motion_id, now,
         parallel_mode, max_parallel_slots,
         resource_conflict_policy],
    )
    await db.commit()
    return {
        "id": graph_id, "motion_id": motion_id,
        "created_at": now, "parallel_mode": parallel_mode,
        "max_parallel_slots": max_parallel_slots,
        "resource_conflict_policy": resource_conflict_policy,
    }


async def get_task_graph(
    db: aiosqlite.Connection, graph_id: str
) -> Optional[dict]:
    """Get TaskGraph by ID, including all tasks."""
    async with db.execute(
        "SELECT * FROM task_graphs WHERE id = ?", [graph_id]
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    graph = dict(row)
    async with db.execute(
        "SELECT * FROM tasks WHERE graph_id = ?", [graph_id]
    ) as cur:
        graph["tasks"] = [_decode_task(r) async for r in cur]
    return graph


async def list_task_graphs(
    db: aiosqlite.Connection,
    limit: int = 100, offset: int = 0,
) -> list[dict]:
    """List all task graphs (without tasks)."""
    sql = "SELECT * FROM task_graphs LIMIT ? OFFSET ?"
    async with db.execute(sql, [limit, offset]) as cur:
        return [dict(r) async for r in cur]


async def get_task_graph_by_motion(
    db: aiosqlite.Connection, motion_id: str
) -> Optional[dict]:
    """Get TaskGraph by motion_id."""
    async with db.execute(
        "SELECT * FROM task_graphs WHERE motion_id = ?", [motion_id]
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return await get_task_graph(db, dict(row)["id"])


async def create_task(db: aiosqlite.Connection, task: TaskNode) -> dict:
    """Insert a single TaskNode row."""
    await db.execute(
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
    await db.commit()
    return _task_to_dict(task)


async def get_task(
    db: aiosqlite.Connection, task_id: str
) -> Optional[dict]:
    """Get a single task by ID."""
    async with db.execute(
        "SELECT * FROM tasks WHERE id = ?", [task_id]
    ) as cur:
        row = await cur.fetchone()
    return _decode_task(row) if row else None


async def list_tasks(
    db: aiosqlite.Connection, graph_id: Optional[str] = None,
    agent_id: Optional[str] = None, status: Optional[str] = None,
    limit: int = 100, offset: int = 0,
) -> list[dict]:
    """List tasks with optional filters."""
    conds, params = [], []
    if graph_id:
        conds.append("graph_id = ?"); params.append(graph_id)
    if agent_id:
        conds.append("assigned_to = ?"); params.append(agent_id)
    if status:
        conds.append("status = ?"); params.append(status)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    sql = f"SELECT * FROM tasks{where} LIMIT ? OFFSET ?"
    params += [limit, offset]
    async with db.execute(sql, params) as cur:
        return [_decode_task(r) async for r in cur]


async def update_task_status(
    db: aiosqlite.Connection, task_id: str, status: str,
    assigned_to: Optional[str] = None,
    error_message: Optional[str] = None,
    artifact_paths: Optional[list[str]] = None,
) -> None:
    """Update task status and related fields."""
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
    await db.execute(
        f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", params
    )
    await db.commit()


async def get_agent_task_count(
    db: aiosqlite.Connection, agent_id: str,
    active_only: bool = True,
) -> int:
    """Count active tasks for an agent (ASSIGNED + RUNNING)."""
    if active_only:
        sql = """SELECT COUNT(*) FROM tasks
                 WHERE assigned_to = ? AND status IN ('assigned','running')"""
    else:
        sql = "SELECT COUNT(*) FROM tasks WHERE assigned_to = ?"
    async with db.execute(sql, [agent_id]) as cur:
        row = await cur.fetchone()
    return row[0] if row else 0


def _decode_task(row: aiosqlite.Row) -> dict:
    """Decode a DB row into a dict, parsing JSON fields."""
    d = dict(row)
    for key in ("required_capabilities", "depends_on",
                "artifact_paths", "workspace_paths"):
        val = d.get(key)
        if isinstance(val, str):
            d[key] = json.loads(val)
    return d


def _task_to_dict(task: TaskNode) -> dict:
    """Convert TaskNode to dict for return value."""
    return task.model_dump(mode="json")
