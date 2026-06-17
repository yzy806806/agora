"""Agent heartbeat and capability storage operations — backend-agnostic."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .dialect import Dialect


async def update_agent_heartbeat(
    db: Any, dialect: Dialect,
    agent_id: str, load: float = 0.0,
    active_tasks: list[str] | None = None,
) -> None:
    """Update agent load and active tasks from HEARTBEAT."""
    active_json = json.dumps(active_tasks or [])
    now = datetime.now(timezone.utc).isoformat()
    sql, params = dialect.render(
        """UPDATE agents
        SET load = ?, active_tasks = ?,
            last_seen_at = ?, is_online = 1
        WHERE agent_id = ?""",
        [load, active_json, now, agent_id])
    await db.execute(sql, params)
    await db.commit()


async def update_agent_capabilities(
    db: Any, dialect: Dialect,
    agent_id: str, capabilities: list[str],
) -> None:
    """Update agent capabilities from HEARTBEAT."""
    caps_json = json.dumps(capabilities)
    sql, params = dialect.render(
        "UPDATE agents SET capabilities = ? "
        "WHERE agent_id = ?",
        [caps_json, agent_id])
    await db.execute(sql, params)
    await db.commit()


async def update_agent_model(
    db: Any, dialect: Dialect,
    agent_id: str, model: str,
) -> None:
    """Update agent model from HEARTBEAT."""
    sql, params = dialect.render(
        "UPDATE agents SET model = ? WHERE agent_id = ?",
        [model, agent_id])
    await db.execute(sql, params)
    await db.commit()


async def list_stale_agents(
    db: Any, dialect: Dialect,
    timeout_seconds: int = 120,
) -> list[dict]:
    """List online agents whose last_seen exceeds timeout_seconds."""
    sql, params = dialect.render(
        "SELECT * FROM agents WHERE is_online = 1", [])
    async with db.execute(sql, params) as cursor:
        rows = [dict(row) async for row in cursor]
    stale = []
    now = datetime.now(timezone.utc)
    for row in rows:
        last_seen = row.get("last_seen_at")
        if last_seen:
            try:
                seen_dt = datetime.fromisoformat(last_seen)
                elapsed = (now - seen_dt).total_seconds()
                if elapsed > timeout_seconds:
                    stale.append(row)
            except (ValueError, TypeError):
                pass
    return stale
