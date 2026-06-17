"""Tests for Phase 10.2c: Token CRUD (storage/tokens.py)."""
from __future__ import annotations

import pytest
import aiosqlite

from agora.coordinator.storage.tokens import (
    save_token, get_token, revoke_token, list_tokens,
)
from agora.coordinator.storage.dialect import Dialect
from agora.coordinator.storage.schema import SCHEMA_SQL

DIALECT = Dialect("sqlite")


@pytest.fixture
async def db(tmp_path):
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA_SQL)
    yield conn
    await conn.close()


@pytest.mark.asyncio
class TestSaveToken:
    async def test_save_basic(self, db):
        result = await save_token(
            db, DIALECT, "tok-1", "hash-1", "agent-1", "agent")
        assert result["token_id"] == "tok-1"
        assert result["principal_id"] == "agent-1"
        assert result["is_revoked"] is False

    async def test_save_with_scopes(self, db):
        result = await save_token(
            db, DIALECT, "tok-2", "hash-2", "admin-1", "admin",
            scopes=["agent:approve", "system:config"])
        assert result["scopes"] == ["agent:approve", "system:config"]

    async def test_save_with_expiry(self, db):
        result = await save_token(
            db, DIALECT, "tok-3", "hash-3", "user-1", "observer",
            expires_at="2026-12-31T23:59:59+00:00")
        assert result["expires_at"] == "2026-12-31T23:59:59+00:00"


@pytest.mark.asyncio
class TestGetToken:
    async def test_get_existing(self, db):
        await save_token(db, DIALECT, "tok-1", "hash-1", "a1", "agent")
        result = await get_token(db, DIALECT, "tok-1")
        assert result is not None
        assert result["principal_id"] == "a1"
        assert result["is_revoked"] is False

    async def test_get_nonexistent(self, db):
        result = await get_token(db, DIALECT, "no-such-token")
        assert result is None


@pytest.mark.asyncio
class TestRevokeToken:
    async def test_revoke_existing(self, db):
        await save_token(db, DIALECT, "tok-1", "hash-1", "a1", "agent")
        ok = await revoke_token(db, DIALECT, "tok-1")
        assert ok is True
        token = await get_token(db, DIALECT, "tok-1")
        assert token is not None
        assert token["is_revoked"] is True

    async def test_revoke_nonexistent(self, db):
        ok = await revoke_token(db, DIALECT, "no-such-token")
        assert ok is False

    async def test_double_revoke(self, db):
        await save_token(db, DIALECT, "tok-1", "hash-1", "a1", "agent")
        await revoke_token(db, DIALECT, "tok-1")
        ok = await revoke_token(db, DIALECT, "tok-1")
        assert ok is False


@pytest.mark.asyncio
class TestListTokens:
    async def test_list_all(self, db):
        await save_token(db, DIALECT, "t1", "h1", "a1", "agent")
        await save_token(db, DIALECT, "t2", "h2", "a2", "admin")
        tokens = await list_tokens(db, DIALECT)
        assert len(tokens) == 2

    async def test_list_by_principal(self, db):
        await save_token(db, DIALECT, "t1", "h1", "a1", "agent")
        await save_token(db, DIALECT, "t2", "h2", "a2", "admin")
        tokens = await list_tokens(db, DIALECT, principal_id="a1")
        assert len(tokens) == 1
        assert tokens[0]["principal_id"] == "a1"

    async def test_list_excludes_revoked(self, db):
        await save_token(db, DIALECT, "t1", "h1", "a1", "agent")
        await revoke_token(db, DIALECT, "t1")
        tokens = await list_tokens(db, DIALECT)
        assert len(tokens) == 0

    async def test_list_include_revoked(self, db):
        await save_token(db, DIALECT, "t1", "h1", "a1", "agent")
        await revoke_token(db, DIALECT, "t1")
        tokens = await list_tokens(db, DIALECT, include_revoked=True)
        assert len(tokens) == 1
