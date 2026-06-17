"""Storage mixin: Assessment + Judgment + Bootstrap CRUD (dialect-aware)."""
from __future__ import annotations

from typing import Optional

from . import assessments as _assessments
from . import judgments as _judgments
from . import bootstrap as _bootstrap
from . import bootstrap_approval as _bootstrap_approval


class StorageAssessmentMixin:
    async def save_assessment(
        self, motion_id: str, round_num: int, result: str,
        consensus_level: str, metrics: dict, rationale: str,
    ) -> int:
        async with self._connection() as db:
            return await _assessments.save_assessment(
                db, self.dialect, motion_id, round_num,
                result, consensus_level, metrics, rationale)

    async def get_latest_assessment(self, motion_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _assessments.get_latest_assessment(
                db, self.dialect, motion_id)

    async def get_assessments(self, motion_id: str) -> list[dict]:
        async with self._connection() as db:
            return await _assessments.get_assessments(
                db, self.dialect, motion_id)


class StorageJudgmentMixin:
    async def record_judgment(
        self, motion_id: str, agent_id: str,
        predicted: str, actual: str, confidence: float,
    ) -> int:
        async with self._connection() as db:
            return await _judgments.record_judgment(
                db, self.dialect, motion_id, agent_id,
                predicted, actual, confidence)

    async def get_agent_stats(self, agent_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _judgments.get_agent_stats(
                db, self.dialect, agent_id)

    async def get_recent_trend(
        self, agent_id: str, limit: int = 5,
    ) -> list[int]:
        async with self._connection() as db:
            return await _judgments.get_recent_trend(
                db, self.dialect, agent_id, limit)

    async def get_judgment_leaderboard(self, limit: int = 10) -> list[dict]:
        async with self._connection() as db:
            return await _judgments.get_leaderboard(db, self.dialect, limit)


class StorageBootstrapMixin:
    async def create_bootstrap_trigger(
        self, trigger_type: str, topic: str,
        source: str, context: str, priority: int = 0,
    ) -> int:
        async with self._connection() as db:
            return await _bootstrap.create_trigger(
                db, self.dialect, trigger_type, topic,
                source, context, priority)

    async def get_pending_bootstrap_triggers(self, limit: int = 10) -> list[dict]:
        async with self._connection() as db:
            return await _bootstrap.get_pending_triggers(
                db, self.dialect, limit)

    async def update_bootstrap_trigger_status(
        self, trigger_id: int, status: str,
    ) -> None:
        async with self._connection() as db:
            await _bootstrap.update_trigger_status(
                db, self.dialect, trigger_id, status)

    async def create_bootstrap_schedule(
        self, name: str, cron_expression: str,
        topic_template: str, next_run: str | None = None,
    ) -> int:
        async with self._connection() as db:
            return await _bootstrap.create_schedule(
                db, self.dialect, name, cron_expression,
                topic_template, next_run)

    async def list_bootstrap_schedules(
        self, enabled_only: bool = False,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _bootstrap.list_schedules(
                db, self.dialect, enabled_only)

    async def create_bootstrap_approval(
        self, motion_id: str, decision: str,
        rationale: str = "", action_items: list[dict] | None = None,
    ) -> int:
        async with self._connection() as db:
            return await _bootstrap_approval.create_approval(
                db, self.dialect, motion_id, decision,
                rationale, action_items)

    async def decide_bootstrap_approval(
        self, approval_id: int, approved: bool,
        approved_by: str = "", feedback: str = "",
    ) -> None:
        async with self._connection() as db:
            await _bootstrap_approval.decide_approval(
                db, self.dialect, approval_id, approved,
                approved_by, feedback)

    async def get_pending_bootstrap_approvals(self, limit: int = 10) -> list[dict]:
        async with self._connection() as db:
            return await _bootstrap_approval.get_pending_approvals(
                db, self.dialect, limit)

    async def register_bootstrap_agent(
        self, agent_id: str, name: str, role: str,
        model: str = "", capabilities: list[str] | None = None,
    ) -> int:
        async with self._connection() as db:
            return await _bootstrap_approval.register_bootstrap_agent(
                db, self.dialect, agent_id, name, role,
                model, capabilities)

    async def list_bootstrap_agents(
        self, active_only: bool = False,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _bootstrap_approval.list_bootstrap_agents(
                db, self.dialect, active_only)
