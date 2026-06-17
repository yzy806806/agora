"""CRUD for execution_slots and resource_locks — backend-agnostic."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .dialect import Dialect
from ..task_models import ExecutionSlot, ResourceLock

logger = logging.getLogger(__name__)


# --- ExecutionSlot CRUD ---

async def create_execution_slot(
    db: Any, dialect: Dialect, slot: ExecutionSlot,
) -> dict:
    sql, params = dialect.render(
        """INSERT INTO execution_slots
        (task_id, agent_id, started_at, status)
        VALUES (?, ?, ?, ?)""",
        [slot.task_id, slot.agent_id,
         slot.started_at.isoformat(), slot.status])
    await db.execute(sql, params)
    await db.commit()
    return slot.model_dump(mode="json")


async def get_execution_slots(
    db: Any, dialect: Dialect,
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict]:
    conds, params = [], []
    if agent_id:
        conds.append("agent_id = ?"); params.append(agent_id)
    if status:
        conds.append("status = ?"); params.append(status)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    sql, params = dialect.render(
        f"SELECT * FROM execution_slots{where}", params)
    async with db.execute(sql, params) as cur:
        return [_decode_slot(r) async for r in cur]


async def update_slot_status(
    db: Any, dialect: Dialect,
    task_id: str, status: str,
) -> None:
    sql, params = dialect.render(
        "UPDATE execution_slots SET status = ? WHERE task_id = ?",
        [status, task_id])
    await db.execute(sql, params)
    await db.commit()


async def delete_execution_slot(
    db: Any, dialect: Dialect, task_id: str,
) -> None:
    sql, params = dialect.render(
        "DELETE FROM execution_slots WHERE task_id = ?", [task_id])
    await db.execute(sql, params)
    await db.commit()


def _decode_slot(row: Any) -> dict:
    return dict(row)


# --- ResourceLock CRUD ---

async def acquire_resource_lock(
    db: Any, dialect: Dialect, lock: ResourceLock,
) -> dict:
    sql, params = dialect.render(
        """INSERT INTO resource_locks
        (resource_path, locked_by, waiting_tasks, lock_type, acquired_at)
        VALUES (?, ?, ?, ?, ?)""",
        [lock.resource_path, lock.locked_by,
         json.dumps(lock.waiting_tasks), lock.lock_type,
         lock.acquired_at.isoformat()])
    await db.execute(sql, params)
    await db.commit()
    return lock.model_dump(mode="json")


async def get_resource_lock(
    db: Any, dialect: Dialect, resource_path: str,
) -> Optional[dict]:
    sql, params = dialect.render(
        "SELECT * FROM resource_locks WHERE resource_path = ?",
        [resource_path])
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
    return _decode_lock(row) if row else None


async def get_locks_by_task(
    db: Any, dialect: Dialect, task_id: str,
) -> list[dict]:
    sql, params = dialect.render(
        "SELECT * FROM resource_locks WHERE locked_by = ?",
        [task_id])
    async with db.execute(sql, params) as cur:
        return [_decode_lock(r) async for r in cur]


async def add_waiting_task(
    db: Any, dialect: Dialect,
    resource_path: str, task_id: str,
) -> None:
    lock = await get_resource_lock(db, dialect, resource_path)
    if not lock:
        return
    waiting = lock.get("waiting_tasks", [])
    if task_id not in waiting:
        waiting.append(task_id)
    sql, params = dialect.render(
        "UPDATE resource_locks SET waiting_tasks = ? "
        "WHERE resource_path = ?",
        [json.dumps(waiting), resource_path])
    await db.execute(sql, params)
    await db.commit()


async def release_resource_lock(
    db: Any, dialect: Dialect, resource_path: str,
) -> None:
    sql, params = dialect.render(
        "DELETE FROM resource_locks WHERE resource_path = ?",
        [resource_path])
    await db.execute(sql, params)
    await db.commit()


async def release_all_locks_for_task(
    db: Any, dialect: Dialect, task_id: str,
) -> None:
    sql, params = dialect.render(
        "DELETE FROM resource_locks WHERE locked_by = ?", [task_id])
    await db.execute(sql, params)
    await db.commit()


def _decode_lock(row: Any) -> dict:
    d = dict(row)
    val = d.get("waiting_tasks")
    if isinstance(val, str):
        d["waiting_tasks"] = json.loads(val)
    return d
