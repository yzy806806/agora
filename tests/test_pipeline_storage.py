"""Tests for pipeline storage CRUD (storage/pipelines.py)."""

import pytest
import pytest_asyncio
import aiosqlite

from agora.coordinator.storage.pipelines import (
    create_pipeline_run, get_pipeline_run, list_pipeline_runs,
    update_pipeline_run, delete_pipeline_run,
)
from agora.coordinator.storage.dialect import Dialect


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "pipelines.db")
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("""CREATE TABLE IF NOT EXISTS pipeline_runs (
        id TEXT PRIMARY KEY, project_id TEXT, idea TEXT,
        motion_id TEXT, graph_id TEXT, phase TEXT,
        started_at TEXT, completed_at TEXT,
        tasks_total INTEGER, tasks_completed INTEGER,
        tasks_failed INTEGER, review_outcome TEXT,
        release_version TEXT, failed_phase TEXT, error TEXT
    )""")
    await conn.commit()
    yield conn
    await conn.close()


@pytest.fixture
def dialect() -> Dialect:
    return Dialect("sqlite")


@pytest.mark.asyncio
async def test_create_and_get(db, dialect):
    row = await create_pipeline_run(db, dialect, "proj-1", "build feature")
    assert row["project_id"] == "proj-1"
    assert row["idea"] == "build feature"
    assert row["phase"] == "discussing"
    fetched = await get_pipeline_run(db, dialect, row["id"])
    assert fetched is not None
    assert fetched["id"] == row["id"]


@pytest.mark.asyncio
async def test_get_not_found(db, dialect):
    assert await get_pipeline_run(db, dialect, "nonexistent") is None


@pytest.mark.asyncio
async def test_list_runs(db, dialect):
    await create_pipeline_run(db, dialect, "p1", "idea1")
    await create_pipeline_run(db, dialect, "p1", "idea2")
    await create_pipeline_run(db, dialect, "p2", "idea3")
    runs = await list_pipeline_runs(db, dialect, project_id="p1")
    assert len(runs) == 2


@pytest.mark.asyncio
async def test_list_by_phase(db, dialect):
    row = await create_pipeline_run(db, dialect, "p1", "idea")
    await update_pipeline_run(db, dialect, row["id"], {"phase": "completed"})
    runs = await list_pipeline_runs(db, dialect, phase="completed")
    assert len(runs) == 1


@pytest.mark.asyncio
async def test_update_run(db, dialect):
    row = await create_pipeline_run(db, dialect, "p1", "idea")
    updated = await update_pipeline_run(db, dialect, row["id"], {
        "phase": "executing", "tasks_total": 5,
    })
    assert updated is not None
    assert updated["phase"] == "executing"
    assert updated["tasks_total"] == 5


@pytest.mark.asyncio
async def test_update_ignores_disallowed(db, dialect):
    row = await create_pipeline_run(db, dialect, "p1", "idea")
    updated = await update_pipeline_run(db, dialect, row["id"], {"id": "hacked"})
    assert updated is not None
    assert updated["id"] == row["id"]


@pytest.mark.asyncio
async def test_delete_run(db, dialect):
    row = await create_pipeline_run(db, dialect, "p1", "idea")
    assert await delete_pipeline_run(db, dialect, row["id"]) is True
    assert await get_pipeline_run(db, dialect, row["id"]) is None


@pytest.mark.asyncio
async def test_delete_nonexistent(db, dialect):
    assert await delete_pipeline_run(db, dialect, "nope") is False
