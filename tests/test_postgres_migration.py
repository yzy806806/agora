"""Postgres integration tests: Migration tool (SQLite -> Postgres).

Tests end-to-end migration: create SQLite DB with sample data,
migrate to Postgres, verify data integrity.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone

import aiosqlite
import pytest

from tests.postgres_test_helper import get_pg_backend, reset_schema

pytestmark = pytest.mark.skipif(
    os.getenv("AGORA_SKIP_POSTGRES_TESTS") == "1",
    reason="AGORA_SKIP_POSTGRES_TESTS=1",
)


async def _create_sqlite_sample(db_path: str) -> None:
    """Create a SQLite DB with sample data for migration testing."""
    from agora.coordinator.storage.schema import SCHEMA_SQL
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA_SQL)
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """INSERT INTO agents
               (agent_id, name, model, capabilities, role,
                registered_at, is_online, agent_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ["mig-agent", "MigBot", "gpt-4",
             json.dumps(["code-review"]), "expert",
             now, 1, "hermes"],
        )
        await db.execute(
            """INSERT INTO motions
               (id, title, description, rounds, status,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ["mot-1", "Test Motion", "Desc", 3, "draft",
             now, now],
        )
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sqlite_to_postgres_migration():
    """Migrate sample data from SQLite to Postgres and verify."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        with tempfile.NamedTemporaryFile(
            suffix=".db", delete=False,
        ) as f:
            db_path = f.name

        try:
            await _create_sqlite_sample(db_path)
            # Read from SQLite
            async with aiosqlite.connect(db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM agents",
                ) as cur:
                    agents = [dict(r) for r in await cur.fetchall()]
                async with db.execute(
                    "SELECT * FROM motions",
                ) as cur:
                    motions = [dict(r) for r in await cur.fetchall()]

            # Write to Postgres
            now = datetime.now(timezone.utc)
            for a in agents:
                caps = json.loads(a["capabilities"]) if isinstance(
                    a["capabilities"], str) else a["capabilities"]
                await backend.execute(
                    """INSERT INTO agents
                       (agent_id, name, model, capabilities, role,
                        registered_at, is_online, agent_type)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                    [a["agent_id"], a["name"], a["model"],
                     caps, a["role"], now, True,
                     a.get("agent_type", "hermes")],
                )
            for m in motions:
                await backend.execute(
                    """INSERT INTO motions
                       (id, title, description, rounds, status,
                        created_at, updated_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    [m["id"], m["title"], m["description"],
                     m["rounds"], m["status"], now, now],
                )

            # Verify row counts
            pg_count = await backend.fetch_val(
                "SELECT COUNT(*) FROM agents"
            )
            assert pg_count == len(agents)
            pg_mot = await backend.fetch_val(
                "SELECT COUNT(*) FROM motions"
            )
            assert pg_mot == len(motions)

            # Verify data integrity
            row = await backend.fetch_one(
                "SELECT * FROM agents WHERE agent_id = $1",
                ["mig-agent"],
            )
            assert row is not None
            assert row["name"] == "MigBot"
            assert row["capabilities"] == ["code-review"]
        finally:
            os.unlink(db_path)
    finally:
        await backend.close()
