"""Tests for multi-tenant infrastructure (Phase 8.2).

Covers: TenantConfig, Tenant, GlobalStorage, StorageManager,
TenantManager, TenantResourceGuard, tenant API routes, DashboardHub.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from agora.coordinator.tenant.models import Tenant, TenantConfig
from agora.coordinator.storage.global_store import GlobalStorage
from agora.coordinator.storage.storage_manager import StorageManager
from agora.coordinator.tenant.manager import TenantManager
from agora.coordinator.tenant.guard import TenantResourceGuard


# --- TenantConfig & Tenant models ---

def test_tenant_config_defaults():
    cfg = TenantConfig()
    assert cfg.max_agents == 10
    assert cfg.max_concurrent_discussions == 3
    assert cfg.default_voting_method == "simple_majority"


def test_tenant_config_round_trip():
    cfg = TenantConfig(max_agents=5, quality_threshold=0.8)
    d = cfg.to_dict()
    cfg2 = TenantConfig.from_dict(d)
    assert cfg2.max_agents == 5
    assert cfg2.quality_threshold == 0.8


def test_tenant_round_trip():
    t = Tenant(tenant_id="acme", name="Acme Corp")
    d = t.to_dict()
    t2 = Tenant.from_dict(d)
    assert t2.tenant_id == "acme"
    assert t2.name == "Acme Corp"
    assert t2.config.max_agents == 10


# --- GlobalStorage ---

@pytest.mark.asyncio
async def test_global_storage_crud():
    with tempfile.TemporaryDirectory() as td:
        db = GlobalStorage(Path(td) / "global.db")
        await db.init_db()
        # Create
        row = await db.create_tenant("test", "Test Co", {"max_agents": 5})
        assert row["tenant_id"] == "test"
        # Get
        got = await db.get_tenant("test")
        assert got is not None
        assert got["name"] == "Test Co"
        # List
        tenants = await db.list_tenants()
        assert len(tenants) == 1
        # Delete
        ok = await db.delete_tenant("test")
        assert ok
        got2 = await db.get_tenant("test")
        assert got2 is None


# --- StorageManager ---

@pytest.mark.asyncio
async def test_storage_manager_default_tenant():
    with tempfile.TemporaryDirectory() as td:
        sm = StorageManager(Path(td))
        await sm.init()
        s = await sm.get_tenant_storage("default")
        assert s is not None
        # Cached
        s2 = sm.get_cached("default")
        assert s2 is s


@pytest.mark.asyncio
async def test_storage_manager_per_tenant_isolation():
    with tempfile.TemporaryDirectory() as td:
        sm = StorageManager(Path(td))
        await sm.init()
        s1 = await sm.get_tenant_storage("tenant-a")
        s2 = await sm.get_tenant_storage("tenant-b")
        assert s1 is not s2
        assert "tenant-a" in str(s1.db_path)
        assert "tenant-b" in str(s2.db_path)


# --- TenantManager ---

@pytest.mark.asyncio
async def test_tenant_manager_crud():
    with tempfile.TemporaryDirectory() as td:
        sm = StorageManager(Path(td))
        await sm.init()
        tm = TenantManager(sm)
        # Create
        t = await tm.create_tenant("acme", "Acme Corp")
        assert t.tenant_id == "acme"
        # Get
        got = await tm.get_tenant("acme")
        assert got is not None
        assert got.name == "Acme Corp"
        # List
        tenants = await tm.list_tenants()
        assert len(tenants) >= 2  # default + acme
        # Delete
        ok = await tm.delete_tenant("acme")
        assert ok
        got2 = await tm.get_tenant("acme")
        assert got2 is None


@pytest.mark.asyncio
async def test_tenant_manager_cannot_delete_default():
    with tempfile.TemporaryDirectory() as td:
        sm = StorageManager(Path(td))
        await sm.init()
        tm = TenantManager(sm)
        with pytest.raises(ValueError, match="Cannot delete"):
            await tm.delete_tenant("default")


@pytest.mark.asyncio
async def test_tenant_manager_invalid_id():
    with tempfile.TemporaryDirectory() as td:
        sm = StorageManager(Path(td))
        await sm.init()
        tm = TenantManager(sm)
        with pytest.raises(ValueError, match="Invalid tenant_id"):
            await tm.create_tenant("BAD ID!", "Bad")


# --- TenantResourceGuard ---

@pytest.mark.asyncio
async def test_guard_agent_limit():
    with tempfile.TemporaryDirectory() as td:
        sm = StorageManager(Path(td))
        await sm.init()
        guard = TenantResourceGuard()
        cfg = TenantConfig(max_agents=0)
        tenant = Tenant(tenant_id="limited", name="Limited", config=cfg)
        storage = await sm.get_tenant_storage("limited")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await guard.check_agent_registration(tenant, storage)
        assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_guard_discussion_limit():
    with tempfile.TemporaryDirectory() as td:
        sm = StorageManager(Path(td))
        await sm.init()
        guard = TenantResourceGuard()
        cfg = TenantConfig(max_concurrent_discussions=0)
        tenant = Tenant(tenant_id="limited", name="Limited", config=cfg)
        storage = await sm.get_tenant_storage("limited")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await guard.check_discussion_start(tenant, storage)
        assert exc_info.value.status_code == 429
