"""Tests for Phase 14+.E.3: Structured task result handling."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agora.coordinator.models import (
    ErrorCategory,
    TaskResultStatus,
)
from agora.coordinator.models import (
    StructuredError,
    TaskMetrics,
    TaskOutput,
    TaskResult,
)
from agora.coordinator.models import MessageType
from agora.coordinator.storage.tasks import save_task_result, get_task_result


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestTaskResultModel:
    def test_success_result(self):
        tr = TaskResult(
            task_id="t1",
            status=TaskResultStatus.SUCCESS,
            output=TaskOutput(
                changed_files=["a.py"],
                artifacts=["/out/report.pdf"],
            ),
        )
        assert tr.task_id == "t1"
        assert tr.status == TaskResultStatus.SUCCESS
        assert tr.output.changed_files == ["a.py"]
        assert tr.output.artifacts == ["/out/report.pdf"]
        assert tr.error is None
        assert tr.metrics is None

    def test_failed_result_with_structured_error(self):
        tr = TaskResult(
            task_id="t2",
            status=TaskResultStatus.FAILED,
            error=StructuredError(
                code="TEST_FAILURE",
                message="2 tests failed",
                category=ErrorCategory.EXECUTION,
                details={"failed_tests": ["test_a", "test_b"]},
                retry_hint="review_test_logic",
            ),
        )
        assert tr.status == TaskResultStatus.FAILED
        assert tr.error is not None
        assert tr.error.code == "TEST_FAILURE"
        assert tr.error.category == ErrorCategory.EXECUTION
        assert tr.error.retry_hint == "review_test_logic"

    def test_partial_result_with_metrics(self):
        tr = TaskResult(
            task_id="t3",
            status=TaskResultStatus.PARTIAL,
            metrics=TaskMetrics(
                wall_time_seconds=45.2, tokens_used=15200,
            ),
        )
        assert tr.status == TaskResultStatus.PARTIAL
        assert tr.metrics is not None
        assert tr.metrics.wall_time_seconds == 45.2

    def test_json_roundtrip(self):
        tr = TaskResult(
            task_id="t4",
            status=TaskResultStatus.SUCCESS,
            output=TaskOutput(changed_files=["a.py"], tests_run=5),
            error=StructuredError(code="E1", message="err"),
            metrics=TaskMetrics(wall_time_seconds=1.0),
        )
        json_str = tr.model_dump_json()
        tr2 = TaskResult.model_validate_json(json_str)
        assert tr2.task_id == "t4"
        assert tr2.status == TaskResultStatus.SUCCESS
        assert tr2.error is not None


class TestStructuredError:
    def test_defaults(self):
        err = StructuredError(code="X", message="bad")
        assert err.category == ErrorCategory.INTERNAL
        assert err.details == {}
        assert err.retry_hint is None

    def test_all_fields(self):
        err = StructuredError(
            code="TIMEOUT",
            message="Took too long",
            category=ErrorCategory.TIMEOUT,
            details={"elapsed_s": 300},
            retry_hint="increase_timeout",
        )
        assert err.category == ErrorCategory.TIMEOUT


# ---------------------------------------------------------------------------
# Storage CRUD tests (with in-memory SQLite)
# ---------------------------------------------------------------------------

@pytest.fixture
async def db_with_task():
    """Create an in-memory DB with schema and a single task row."""
    import aiosqlite
    from agora.coordinator.storage.schema import SCHEMA_SQL
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await db.executescript(SCHEMA_SQL)
    # Insert agent + motion + graph + task
    await db.execute(
        "INSERT INTO agents (agent_id, name, registered_at) "
        "VALUES ('a1', 'Agent1', '2025-01-01T00:00:00')"
    )
    await db.execute(
        "INSERT INTO motions (id, title, status, created_at, updated_at) "
        "VALUES ('m1', 'Test', 'draft', '2025-01-01T00:00:00', "
        "'2025-01-01T00:00:00')"
    )
    await db.execute(
        "INSERT INTO task_graphs (id, motion_id, created_at) "
        "VALUES ('g1', 'm1', '2025-01-01T00:00:00')"
    )
    await db.execute(
        "INSERT INTO tasks (id, graph_id, motion_id, title, status, "
        "created_at) VALUES ('t1', 'g1', 'm1', 'Task1', 'running', "
        "'2025-01-01T00:00:00')"
    )
    await db.commit()
    yield db
    await db.close()


class TestStorageTaskResult:
    @pytest.mark.asyncio
    async def test_save_and_get(self, db_with_task):
        from agora.coordinator.storage.dialect import SQLITE_DIALECT
        result = TaskResult(
            task_id="t1",
            status=TaskResultStatus.SUCCESS,
            output=TaskOutput(tests_run=12),
            metrics=TaskMetrics(wall_time_seconds=5.3),
        )
        await save_task_result(
            db_with_task, SQLITE_DIALECT, "t1",
            result.model_dump_json(),
        )
        got = await get_task_result(db_with_task, SQLITE_DIALECT, "t1")
        assert got is not None
        assert got["task_id"] == "t1"
        assert got["status"] == "success"
        assert got["output"]["tests_run"] == 12
        assert got["metrics"]["wall_time_seconds"] == 5.3

    @pytest.mark.asyncio
    async def test_get_missing_task(self, db_with_task):
        from agora.coordinator.storage.dialect import SQLITE_DIALECT
        got = await get_task_result(db_with_task, SQLITE_DIALECT, "nonexistent")
        assert got is None

    @pytest.mark.asyncio
    async def test_get_task_without_result(self, db_with_task):
        from agora.coordinator.storage.dialect import SQLITE_DIALECT
        got = await get_task_result(db_with_task, SQLITE_DIALECT, "t1")
        assert got is None


# ---------------------------------------------------------------------------
# WS handler tests
# ---------------------------------------------------------------------------

class TestHandleTaskResult:
    @pytest.mark.asyncio
    async def test_success_result_stored(self):
        from agora.coordinator.task_exec import handle_task_result
        storage = MagicMock()
        storage.get_task = AsyncMock(return_value={
            "id": "t1", "status": "running", "motion_id": "m1",
        })
        storage.save_task_result = AsyncMock()
        storage.update_task_status = AsyncMock()
        storage.log_event = AsyncMock()
        hub = MagicMock()
        hub.send = AsyncMock()
        with patch("agora.coordinator.task_verify.verify_task",
                    new_callable=AsyncMock):
            await handle_task_result(
                "a1",
                {
                    "task_id": "t1",
                    "status": "success",
                    "output": {"tests_run": 5},
                    "metrics": {"wall_time_seconds": 10.0},
                },
                storage, hub,
            )
        storage.save_task_result.assert_called_once()
        call_args = storage.save_task_result.call_args
        assert call_args[0][0] == "t1"
        stored_json = call_args[0][1]
        parsed = json.loads(stored_json)
        assert parsed["status"] == "success"

    @pytest.mark.asyncio
    async def test_failed_result_triggers_v1_failed(self):
        from agora.coordinator.task_exec import handle_task_result
        storage = MagicMock()
        storage.get_task = AsyncMock(return_value={
            "id": "t1", "status": "running", "motion_id": "m1",
        })
        storage.save_task_result = AsyncMock()
        storage.update_task_status = AsyncMock()
        storage.log_event = AsyncMock()
        hub = MagicMock()
        hub.send = AsyncMock()
        await handle_task_result(
            "a1",
            {
                "task_id": "t1",
                "status": "failed",
                "error": {
                    "code": "TEST_FAILURE",
                    "message": "2 tests failed",
                    "category": "execution",
                },
            },
            storage, hub,
        )
        # Should delegate to handle_task_status with v1 "failed"
        storage.update_task_status.assert_called_once()
        call_args = storage.update_task_status.call_args
        assert call_args[0][1] == "failed"

    @pytest.mark.asyncio
    async def test_missing_task_id_sends_error(self):
        from agora.coordinator.task_exec import handle_task_result
        storage = MagicMock()
        hub = MagicMock()
        hub.send = AsyncMock()
        await handle_task_result("a1", {}, storage, hub)
        hub.send.assert_called_once()
        msg = hub.send.call_args[0][1]
        assert msg["payload"]["code"] == "missing_task_id"


# ---------------------------------------------------------------------------
# MessageType enum test
# ---------------------------------------------------------------------------

class TestMessageTypeV2:
    def test_task_result_exists(self):
        assert MessageType.TASK_RESULT.value == "TASK_RESULT"
