"""Tests for Phase 10.2e: RBAC Storage + Migration."""
from __future__ import annotations

import pytest
import aiosqlite

from agora.coordinator.storage.rbac import (
    create_token, get_token_by_hash, revoke_token,
    get_role, list_roles, seed_default_roles,
    log_audit, query_audit,
)
from agora.coordinator.storage.dialect import Dialect
from agora.coordinator.storage.schema import SCHEMA_SQL, DEFAULT_ROLES


@pytest.fixture
async def db(tmp_path):
    """In-memory DB with RBAC tables created."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA_SQL)
    await seed_default_roles(conn)
    yield conn
    await conn.close()


@pytest.fixture
def dialect() -> Dialect:
    """SQLite dialect for test CRUD calls."""
    return Dialect("sqlite")


class TestSeedDefaultRoles:
    async def test_seeds_three_roles(self, db, dialect) -> None:
        roles = await list_roles(db, dialect)
        names = {r["name"] for r in roles}
        assert names == {"admin", "agent", "observer"}

    async def test_idempotent(self, db, dialect) -> None:
        await seed_default_roles(db)
        roles = await list_roles(db, dialect)
        assert len(roles) == 3


class TestGetRole:
    async def test_existing_role(self, db, dialect) -> None:
        role = await get_role(db, dialect, "admin")
        assert role is not None
        assert role["name"] == "admin"
        assert "agent:approve" in role["permissions"]

    async def test_missing_role(self, db, dialect) -> None:
        role = await get_role(db, dialect, "nonexistent")
        assert role is None


class TestTokenCRUD:
    async def test_create_and_lookup(self, db, dialect) -> None:
        tok = await create_token(
            db, dialect, "agent-1", "agent", "hash123", "tid-1")
        assert tok["principal_id"] == "agent-1"
        found = await get_token_by_hash(db, dialect, "hash123")
        assert found is not None
        assert found["principal_id"] == "agent-1"

    async def test_revoke_token(self, db, dialect) -> None:
        tok = await create_token(
            db, dialect, "agent-2", "observer", "hash456", "tid-2")
        row = await get_token_by_hash(db, dialect, "hash456")
        assert row is not None
        await revoke_token(db, dialect, row["id"])
        found = await get_token_by_hash(db, dialect, "hash456")
        assert found is None

    async def test_unknown_hash(self, db, dialect) -> None:
        found = await get_token_by_hash(db, dialect, "nope")
        assert found is None


class TestAuditLog:
    async def test_log_and_query(self, db, dialect) -> None:
        aid = await log_audit(
            db, dialect, "auth", "user-1", "login", resource="/api",
            actor_role="admin", details={"ip": "1.2.3.4"})
        assert aid > 0
        rows = await query_audit(db, dialect)
        assert len(rows) == 1
        assert rows[0]["actor_id"] == "user-1"

    async def test_filter_by_actor(self, db, dialect) -> None:
        await log_audit(db, dialect, "auth", "user-1", "login")
        await log_audit(db, dialect, "auth", "user-2", "login")
        rows = await query_audit(db, dialect, actor_id="user-2")
        assert len(rows) == 1

    async def test_filter_by_event_type(self, db, dialect) -> None:
        await log_audit(db, dialect, "auth", "u1", "login")
        await log_audit(db, dialect, "task", "u1", "execute")
        rows = await query_audit(db, dialect, event_type="task")
        assert len(rows) == 1
