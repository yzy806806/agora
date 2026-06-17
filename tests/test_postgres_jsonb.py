"""Postgres integration tests: JSONB queries.

Tests JSONB-specific queries like @> containment operator
and GIN index usage.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from tests.postgres_test_helper import get_pg_backend, reset_schema

pytestmark = pytest.mark.skipif(
    os.getenv("AGORA_SKIP_POSTGRES_TESTS") == "1",
    reason="AGORA_SKIP_POSTGRES_TESTS=1",
)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_jsonb_containment_query():
    """capabilities @> '["code-review"]' finds matching agents."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        await backend.execute(
            """INSERT INTO agents
               (agent_id, name, model, capabilities,
                role, registered_at, is_online)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            ["cap-1", "Reviewer", "gpt-4",
             ["code-review", "testing"], "expert", now, True],
        )
        await backend.execute(
            """INSERT INTO agents
               (agent_id, name, model, capabilities,
                role, registered_at, is_online)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            ["cap-2", "Writer", "gpt-4",
             ["writing", "translation"], "expert", now, False],
        )
        rows = await backend.fetch_all(
            "SELECT * FROM agents WHERE capabilities @> $1",
            [['code-review']],
        )
        assert len(rows) == 1
        assert rows[0]["agent_id"] == "cap-1"
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_jsonb_containment_no_match():
    """capabilities @> '["nonexistent"]' returns empty."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        await backend.execute(
            """INSERT INTO agents
               (agent_id, name, model, capabilities,
                role, registered_at, is_online)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            ["cap-3", "Bot", "test", ["writing"],
             "expert", now, False],
        )
        rows = await backend.fetch_all(
            "SELECT * FROM agents WHERE capabilities @> $1",
            [['nonexistent']],
        )
        assert len(rows) == 0
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_jsonb_task_required_caps():
    """tasks.required_capabilities @> query works."""
    backend = await get_pg_backend()
    try:
        await reset_schema(backend)
        now = datetime.now(timezone.utc)
        await backend.execute(
            """INSERT INTO tasks
               (id, title, status, required_capabilities,
                depends_on, created_at)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            ["task-1", "Review PR", "pending",
             ["code-review", "security"], [], now],
        )
        rows = await backend.fetch_all(
            "SELECT * FROM tasks WHERE required_capabilities @> $1",
            [['code-review']],
        )
        assert len(rows) == 1
        assert rows[0]["id"] == "task-1"
    finally:
        await backend.close()
