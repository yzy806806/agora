"""Tests for Phase 14 workspace schema migration (14→15, 15→16)."""
import pytest
import aiosqlite
from agora.coordinator.storage.schema import (
    SCHEMA_VERSION, MIGRATION_14_TO_15, MIGRATION_15_TO_16, SCHEMA_SQL,
)
from agora.coordinator.storage import Storage


@pytest.mark.asyncio
async def test_schema_version_is_16():
    assert SCHEMA_VERSION == 16


@pytest.mark.asyncio
async def test_migration_creates_file_nodes(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    for stmt in MIGRATION_14_TO_15:
        await conn.execute(stmt)
    await conn.commit()
    # Insert a file_node
    await conn.execute(
        "INSERT INTO file_nodes "
        "(id, project_id, path, name, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ["n1", "proj1", "/src/main.py", "main.py",
         "agent-1", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"],
    )
    await conn.commit()
    cur = await conn.execute("SELECT * FROM file_nodes WHERE id = ?", ["n1"])
    row = await cur.fetchone()
    assert row is not None
    assert row["project_id"] == "proj1"
    assert row["file_type"] == "file"
    assert row["version"] == 1
    await conn.close()


@pytest.mark.asyncio
async def test_migration_creates_file_locks(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    for stmt in MIGRATION_14_TO_15:
        await conn.execute(stmt)
    await conn.commit()
    # Insert a file_node first
    await conn.execute(
        "INSERT INTO file_nodes "
        "(id, project_id, path, name, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ["n1", "proj1", "/src/main.py", "main.py",
         "agent-1", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"],
    )
    # Insert a file_lock
    await conn.execute(
        "INSERT INTO file_locks "
        "(id, file_id, project_id, path, lock_type, held_by, "
        "acquired_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ["l1", "n1", "proj1", "/src/main.py", "write",
         "agent-2", "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"],
    )
    await conn.commit()
    cur = await conn.execute("SELECT * FROM file_locks WHERE id = ?", ["l1"])
    row = await cur.fetchone()
    assert row is not None
    assert row["lock_type"] == "write"
    assert row["held_by"] == "agent-2"
    await conn.close()


@pytest.mark.asyncio
async def test_unique_project_path_constraint(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = await aiosqlite.connect(db_path)
    for stmt in MIGRATION_14_TO_15:
        await conn.execute(stmt)
    await conn.commit()
    base = ("INSERT INTO file_nodes "
            "(id, project_id, path, name, created_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)")
    await conn.execute(base,
        ["n1", "proj1", "/a.py", "a.py", "a1", "t1", "t1"])
    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(base,
            ["n2", "proj1", "/a.py", "a.py", "a2", "t2", "t2"])
    await conn.close()


@pytest.mark.asyncio
async def test_full_init_db_creates_workspace_tables(tmp_path):
    db_path = str(tmp_path / "full.db")
    storage = Storage(db_path)
    await storage.init_db()
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('file_nodes', 'file_locks')")
        tables = [r[0] for r in await cur.fetchall()]
    assert "file_nodes" in tables
    assert "file_locks" in tables


@pytest.mark.asyncio
async def test_cascade_delete_lock_on_node_delete(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA foreign_keys = ON")
    for stmt in MIGRATION_14_TO_15:
        await conn.execute(stmt)
    await conn.commit()
    await conn.execute(
        "INSERT INTO file_nodes "
        "(id, project_id, path, name, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ["n1", "p1", "/x.py", "x.py", "a1", "t", "t"])
    await conn.execute(
        "INSERT INTO file_locks "
        "(id, file_id, project_id, path, lock_type, held_by, "
        "acquired_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ["l1", "n1", "p1", "/x.py", "read", "a2", "t", "t"])
    await conn.commit()
    await conn.execute("DELETE FROM file_nodes WHERE id = ?", ["n1"])
    await conn.commit()
    cur = await conn.execute("SELECT COUNT(*) FROM file_locks")
    count = (await cur.fetchone())[0]
    assert count == 0
    await conn.close()


@pytest.mark.asyncio
async def test_migration_15_to_16_adds_workspace_paths(tmp_path):
    db_path = str(tmp_path / "test.db")
    storage = Storage(db_path)
    await storage.init_db()
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("PRAGMA table_info(tasks)")
        cols = {r["name"] for r in await cur.fetchall()}
    assert "workspace_paths" in cols
