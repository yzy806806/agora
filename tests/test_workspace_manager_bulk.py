"""Tests for WorkspaceManager bulk pull_files / push_files (Phase 14.2d)."""

from __future__ import annotations

import pytest

from conftest_workspace import mgr  # noqa: F401 — fixture

PID = "proj1"
AID = "agent-a"
AID2 = "agent-b"


class TestPullFiles:
    @pytest.mark.asyncio
    async def test_pull_multiple_files(self, mgr):
        await mgr.write_file(PID, "a.txt", b"aaa", AID)
        await mgr.write_file(PID, "b.txt", b"bbb", AID)
        result = await mgr.pull_files(PID, ["a.txt", "b.txt"], AID)
        assert result == {"a.txt": b"aaa", "b.txt": b"bbb"}

    @pytest.mark.asyncio
    async def test_pull_nonexistent_file_skipped(self, mgr):
        await mgr.write_file(PID, "a.txt", b"aaa", AID)
        result = await mgr.pull_files(
            PID, ["a.txt", "missing.txt"], AID,
        )
        assert result == {"a.txt": b"aaa"}
        assert "missing.txt" not in result


class TestPushFiles:
    @pytest.mark.asyncio
    async def test_push_multiple_files(self, mgr):
        nodes = await mgr.push_files(
            PID, {"x.txt": b"xxx", "y.txt": b"yyy"}, AID,
        )
        assert len(nodes) == 2
        _, xa = await mgr.read_file(PID, "x.txt", AID)
        _, ya = await mgr.read_file(PID, "y.txt", AID)
        assert xa == b"xxx"
        assert ya == b"yyy"

    @pytest.mark.asyncio
    async def test_push_with_lock_check(self, mgr):
        await mgr.write_file(PID, "locked.txt", b"old", AID)
        lock = await mgr.locks.acquire_lock(
            PID, "locked.txt", AID2, "write",
        )
        with pytest.raises(PermissionError, match="locked by another"):
            await mgr.push_files(
                PID, {"locked.txt": b"new"}, AID,
            )
        await mgr.locks.release_lock(lock.id, AID2)

    @pytest.mark.asyncio
    async def test_push_rollback_on_failure(self, mgr):
        await mgr.write_file(PID, "target.txt", b"old", AID)
        lock = await mgr.locks.acquire_lock(
            PID, "target.txt", AID2, "write",
        )
        with pytest.raises(PermissionError):
            await mgr.push_files(
                PID, {"ok.txt": b"new", "target.txt": b"new2"}, AID,
            )
        # ok.txt should NOT exist (rolled back)
        with pytest.raises(FileNotFoundError):
            await mgr.read_file(PID, "ok.txt", AID)
        # target.txt should be unchanged
        _, content = await mgr.read_file(PID, "target.txt", AID)
        assert content == b"old"
        await mgr.locks.release_lock(lock.id, AID2)
