"""SQLite storage layer for the Agora Coordinator service.

Provides the Storage class that manages database connections and
delegates CRUD operations to sub-modules.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from . import agents as _agents
from . import agent_heartbeat as _agent_hb
from . import assessments as _assessments
from . import artifacts as _artifacts
from . import bootstrap as _bootstrap
from . import bootstrap_approval as _bootstrap_approval
from . import events as _events
from . import judgments as _judgments
from . import messages as _messages
from . import motions as _motions
from . import sessions as _sessions
from . import tasks as _tasks
from . import votes as _votes
from . import parallel as _parallel
from . import pipelines as _pipelines
from . import notifications as _notifications
from . import rbac as _rbac
from . import tokens as _tokens
from . import sessions as _sessions
from .schema import SCHEMA_SQL, SCHEMA_VERSION, MIGRATION_6_TO_7, MIGRATION_7_TO_8, MIGRATION_8_TO_9, MIGRATION_9_TO_10, MIGRATION_10_TO_11, MIGRATION_11_TO_12, MIGRATION_12_TO_13, MIGRATION_12_TO_13_PIPELINES, MIGRATION_14_TO_15, MIGRATION_15_TO_16

logger = logging.getLogger(__name__)


class Storage:
    """SQLite storage layer with async connection management."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    @asynccontextmanager
    async def _connection(self):
        """Async database connection context manager with WAL mode."""
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            await conn.close()

    async def init_db(self) -> None:
        """Initialize database tables and run pending migrations."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA_SQL)
            await db.execute(
                """CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY, applied_at TEXT)"""
            )
            # Check current version and run migrations
            async with db.execute(
                "SELECT MAX(version) FROM schema_version"
            ) as cur:
                row = await cur.fetchone()
            current_ver = row[0] if row and row[0] else SCHEMA_VERSION

            if current_ver < 7:
                for stmt in MIGRATION_6_TO_7:
                    await db.execute(stmt)
                logger.info("Applied migration 6→7 (Phase 9.3 agent columns)")

            if current_ver < 8:
                for stmt in MIGRATION_7_TO_8:
                    await db.execute(stmt)
                logger.info("Applied migration 7→8 (Phase 9.4 rate_limit_usage)")

            if current_ver < 9:
                for stmt in MIGRATION_8_TO_9:
                    await db.execute(stmt)
                logger.info(
                    "Applied migration 8→9 (Phase 10 parallel + RBAC)")

            if current_ver < 10:
                for stmt in MIGRATION_9_TO_10:
                    await db.execute(stmt)
                logger.info(
                    "Applied migration 9→10 (Phase 11.1b agent config)")

            if current_ver < 11:
                for stmt in MIGRATION_10_TO_11:
                    await db.execute(stmt)
                logger.info(
                    "Applied migration 10→11 (Phase 12.5a session_records)")

            if current_ver < 12:
                for stmt in MIGRATION_11_TO_12:
                    await db.execute(stmt)
                logger.info(
                    "Applied migration 11→12 (Phase 13 pipeline_runs)")

            if current_ver < 13:
                for stmt in MIGRATION_12_TO_13:
                    await db.execute(stmt)
                logger.info(
                    "Applied migration 12→13 (Phase 13 notifications)")

            if current_ver < 14:
                for stmt in MIGRATION_12_TO_13_PIPELINES:
                    await db.execute(stmt)
                logger.info(
                    "Applied migration 13→14 (Phase 13b failed_phase)")

            if current_ver < 15:
                for stmt in MIGRATION_14_TO_15:
                    await db.execute(stmt)
                logger.info(
                    "Applied migration 14→15 (Phase 14 workspace tables)")

            if current_ver < 16:
                for stmt in MIGRATION_15_TO_16:
                    await db.execute(stmt)
                logger.info(
                    "Applied migration 15→16 (Phase 14.5b workspace_paths)")

            await db.execute(
                "INSERT OR IGNORE INTO schema_version VALUES (?, ?)",
                [SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()],
            )
            await db.commit()

            # Seed default RBAC roles if roles table is empty
            async with db.execute("SELECT COUNT(*) FROM roles") as cur:
                row = await cur.fetchone()
            if row and row[0] == 0:
                await _rbac.seed_default_roles(db)
        logger.info("Database initialized at %s", self.db_path)

    # --- Agent CRUD ---

    async def register_agent(self, agent_id: str, name: str, model: str = "unknown",
                             capabilities: list[str] | None = None,
                             role: str = "participant",
                             agent_type: str = "hermes",
                             max_concurrent_tasks: int = 2,
                             agent_token: str = "",
                             is_approved: bool = False,
                             approval_status: str = "pending",
                             tpm_limit: int = 10000,
                             tpm_burst_factor: float = 1.5,
                             **kwargs) -> dict:
        async with self._connection() as db:
            return await _agents.register_agent(
                db, agent_id, name, model,
                capabilities=capabilities, role=role,
                agent_type=agent_type,
                max_concurrent_tasks=max_concurrent_tasks,
                agent_token=agent_token,
                is_approved=is_approved,
                approval_status=approval_status,
                tpm_limit=tpm_limit,
                tpm_burst_factor=tpm_burst_factor,
            )

    async def get_agent(self, agent_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _agents.get_agent(db, agent_id)

    async def get_agent_by_token(self, token: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _agents.get_agent_by_token(db, token)

    async def list_agents(self, online_only: bool = False) -> list[dict]:
        async with self._connection() as db:
            return await _agents.list_agents(db, online_only)

    async def set_agent_online(self, agent_id: str, online: bool) -> None:
        async with self._connection() as db:
            await _agents.set_agent_online(db, agent_id, online)

    async def deregister_agent(self, agent_id: str) -> None:
        async with self._connection() as db:
            await _agents.deregister_agent(db, agent_id)

    async def set_agent_approval(
        self, agent_id: str, is_approved: bool, approval_status: str,
    ) -> None:
        """Approve/reject/suspend an agent (Phase 9.3)."""
        async with self._connection() as db:
            await _agents.set_agent_approval(
                db, agent_id, is_approved, approval_status)

    async def update_agent_tpm_config(
        self, agent_id: str,
        tpm_limit: int | None = None,
        tpm_burst_factor: float | None = None,
    ) -> None:
        """Persist agent TPM config to DB (Phase 9.4)."""
        async with self._connection() as db:
            await _agents.update_agent_tpm_config(
                db, agent_id, tpm_limit, tpm_burst_factor)

    async def update_agent_config(
        self, agent_id: str, *,
        tpm_limit: int | None = None,
        tpm_burst_factor: float | None = None,
        max_concurrent_tasks: int | None = None,
        role: str | None = None,
        allowed_discussion_roles: list[str] | None = None,
    ) -> None:
        """Persist agent config to DB (Phase 11.1b)."""
        async with self._connection() as db:
            await _agents.update_agent_config(
                db, agent_id,
                tpm_limit=tpm_limit,
                tpm_burst_factor=tpm_burst_factor,
                max_concurrent_tasks=max_concurrent_tasks,
                role=role,
                allowed_discussion_roles=allowed_discussion_roles,
            )

    async def update_agent_token(
        self, agent_id: str, new_token: str,
    ) -> None:
        """Replace agent_token in DB (Phase 11.1b token rotation)."""
        async with self._connection() as db:
            await db.execute(
                "UPDATE agents SET agent_token = ? WHERE agent_id = ?",
                [new_token, agent_id],
            )
            await db.commit()

    # --- Motion CRUD ---

    async def create_motion(self, title: str, description: str,
                            rounds: int = 3,
                            voting_method: str = "simple_majority",
                            context: str = "") -> dict:
        async with self._connection() as db:
            return await _motions.create_motion(
                db, title, description, rounds, voting_method, context)

    async def get_motion(self, motion_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _motions.get_motion(db, motion_id)

    async def list_motions(self, status: Optional[str] = None,
                           limit: int = 100, offset: int = 0) -> list[dict]:
        async with self._connection() as db:
            return await _motions.list_motions(db, status, limit, offset)

    async def update_motion_status(self, motion_id: str, status: str,
                                   decision: Optional[str] = None,
                                   rationale: Optional[str] = None,
                                   action_items: Optional[list[str]] = None) -> None:
        async with self._connection() as db:
            await _motions.update_motion_status(
                db, motion_id, status, decision, rationale, action_items)

    async def increment_round(self, motion_id: str) -> int:
        async with self._connection() as db:
            return await _motions.increment_round(db, motion_id)

    # --- Message CRUD ---

    async def add_message(self, motion_id: str, agent_id: str,
                          round_num: int, stance: str, content: str,
                          evidence: list[dict] | None = None) -> int:
        async with self._connection() as db:
            return await _messages.add_message(
                db, motion_id, agent_id, round_num, stance, content, evidence)

    async def get_messages(self, motion_id: str,
                           round_num: Optional[int] = None,
                           agent_id: Optional[str] = None) -> list[dict]:
        async with self._connection() as db:
            return await _messages.get_messages(db, motion_id, round_num, agent_id)

    async def count_messages_by_round(self, motion_id: str,
                                      round_num: int) -> int:
        async with self._connection() as db:
            return await _messages.count_messages_by_round(db, motion_id, round_num)

    # --- Vote CRUD ---

    async def add_vote(self, motion_id: str, agent_id: str, vote: str,
                       confidence: float = 1.0,
                       reason: Optional[str] = None,
                       vote_type: str = "binary",
                       vote_data: Optional[str] = None) -> int:
        async with self._connection() as db:
            return await _votes.add_vote(
                db, motion_id, agent_id, vote, confidence, reason,
                vote_type, vote_data)

    async def get_votes(self, motion_id: str) -> list[dict]:
        async with self._connection() as db:
            return await _votes.get_votes(db, motion_id)

    async def has_voted(self, motion_id: str, agent_id: str) -> bool:
        async with self._connection() as db:
            return await _votes.has_voted(db, motion_id, agent_id)

    async def count_votes(self, motion_id: str) -> dict[str, int]:
        async with self._connection() as db:
            return await _votes.count_votes(db, motion_id)

    async def get_vote_summary(self, motion_id: str) -> dict:
        async with self._connection() as db:
            return await _votes.get_vote_summary(db, motion_id)

    # --- Statistics ---

    async def get_active_motion_count(self) -> int:
        async with self._connection() as db:
            return await _votes.get_active_motion_count(db)

    async def get_participant_count(self) -> int:
        async with self._connection() as db:
            return await _votes.get_participant_count(db)

    # --- Assessment CRUD ---

    async def save_assessment(
        self, motion_id: str, round_num: int, result: str,
        consensus_level: str, metrics: dict, rationale: str,
    ) -> int:
        async with self._connection() as db:
            return await _assessments.save_assessment(
                db, motion_id, round_num, result,
                consensus_level, metrics, rationale)

    async def get_latest_assessment(
        self, motion_id: str,
    ) -> Optional[dict]:
        async with self._connection() as db:
            return await _assessments.get_latest_assessment(db, motion_id)

    async def get_assessments(
        self, motion_id: str,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _assessments.get_assessments(db, motion_id)

    # --- Judgment CRUD ---

    async def record_judgment(
        self, motion_id: str, agent_id: str,
        predicted: str, actual: str, confidence: float,
    ) -> int:
        async with self._connection() as db:
            return await _judgments.record_judgment(
                db, motion_id, agent_id,
                predicted, actual, confidence)

    async def get_agent_stats(self, agent_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _judgments.get_agent_stats(db, agent_id)

    async def get_recent_trend(
        self, agent_id: str, limit: int = 5,
    ) -> list[int]:
        async with self._connection() as db:
            return await _judgments.get_recent_trend(db, agent_id, limit)

    async def get_judgment_leaderboard(
        self, limit: int = 10,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _judgments.get_leaderboard(db, limit)

    # --- Bootstrap Trigger CRUD ---

    async def create_bootstrap_trigger(
        self, trigger_type: str, topic: str,
        source: str, context: str, priority: int = 0,
    ) -> int:
        async with self._connection() as db:
            return await _bootstrap.create_trigger(
                db, trigger_type, topic, source, context, priority)

    async def get_pending_bootstrap_triggers(
        self, limit: int = 10,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _bootstrap.get_pending_triggers(db, limit)

    async def update_bootstrap_trigger_status(
        self, trigger_id: int, status: str,
    ) -> None:
        async with self._connection() as db:
            await _bootstrap.update_trigger_status(db, trigger_id, status)

    # --- Bootstrap Schedule CRUD ---

    async def create_bootstrap_schedule(
        self, name: str, cron_expression: str,
        topic_template: str, next_run: str | None = None,
    ) -> int:
        async with self._connection() as db:
            return await _bootstrap.create_schedule(
                db, name, cron_expression, topic_template, next_run)

    async def list_bootstrap_schedules(
        self, enabled_only: bool = False,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _bootstrap.list_schedules(db, enabled_only)

    # --- Bootstrap Approval CRUD ---

    async def create_bootstrap_approval(
        self, motion_id: str, decision: str,
        rationale: str = "", action_items: list[dict] | None = None,
    ) -> int:
        async with self._connection() as db:
            return await _bootstrap_approval.create_approval(
                db, motion_id, decision, rationale, action_items)

    async def decide_bootstrap_approval(
        self, approval_id: int, approved: bool,
        approved_by: str = "", feedback: str = "",
    ) -> None:
        async with self._connection() as db:
            await _bootstrap_approval.decide_approval(
                db, approval_id, approved, approved_by, feedback)

    async def get_pending_bootstrap_approvals(
        self, limit: int = 10,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _bootstrap_approval.get_pending_approvals(
                db, limit)

    # --- Bootstrap Agent CRUD ---

    async def register_bootstrap_agent(
        self, agent_id: str, name: str, role: str,
        model: str = "", capabilities: list[str] | None = None,
    ) -> int:
        async with self._connection() as db:
            return await _bootstrap_approval.register_bootstrap_agent(
                db, agent_id, name, role, model, capabilities)

    async def list_bootstrap_agents(
        self, active_only: bool = False,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _bootstrap_approval.list_bootstrap_agents(
                db, active_only)

    # --- Event CRUD (Phase 8 Dashboard) ---

    async def log_event(
        self, event_type: str, detail: str = "",
        motion_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> int:
        async with self._connection() as db:
            return await _events.log_event(
                db, event_type, detail, motion_id, agent_id)

    async def get_events(
        self, since: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _events.get_events(
                db, since, event_type, limit)

    async def get_timeline(self, motion_id: str) -> list[dict]:
        async with self._connection() as db:
            return await _events.get_timeline(db, motion_id)

    # --- Task CRUD (Phase 9) ---

    async def create_task_graph(
        self, graph_id: str, motion_id: str,
        parallel_mode: str = "auto",
        max_parallel_slots: int = 10,
        resource_conflict_policy: str = "warn",
    ) -> dict:
        async with self._connection() as db:
            return await _tasks.create_task_graph(
                db, graph_id, motion_id,
                parallel_mode=parallel_mode,
                max_parallel_slots=max_parallel_slots,
                resource_conflict_policy=resource_conflict_policy,
            )

    async def get_task_graph(self, graph_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _tasks.get_task_graph(db, graph_id)

    async def list_task_graphs(
        self, limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _tasks.list_task_graphs(db, limit, offset)

    async def get_task_graph_by_motion(
        self, motion_id: str
    ) -> Optional[dict]:
        async with self._connection() as db:
            return await _tasks.get_task_graph_by_motion(db, motion_id)

    async def create_task(self, task) -> dict:
        async with self._connection() as db:
            return await _tasks.create_task(db, task)

    async def get_task(self, task_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _tasks.get_task(db, task_id)

    async def list_tasks(self, **kwargs) -> list[dict]:
        async with self._connection() as db:
            return await _tasks.list_tasks(db, **kwargs)

    async def update_task_status(
        self, task_id: str, status: str, **kwargs
    ) -> None:
        async with self._connection() as db:
            await _tasks.update_task_status(
                db, task_id, status, **kwargs)

    async def get_agent_task_count(
        self, agent_id: str, active_only: bool = True
    ) -> int:
        async with self._connection() as db:
            return await _tasks.get_agent_task_count(
                db, agent_id, active_only)

    # --- Agent Heartbeat CRUD (Phase 9.3c) ---

    async def update_agent_heartbeat(
        self, agent_id: str, load: float = 0.0,
        active_tasks: list[str] | None = None,
    ) -> None:
        async with self._connection() as db:
            await _agent_hb.update_agent_heartbeat(
                db, agent_id, load, active_tasks)

    async def update_agent_capabilities(
        self, agent_id: str, capabilities: list[str],
    ) -> None:
        async with self._connection() as db:
            await _agent_hb.update_agent_capabilities(
                db, agent_id, capabilities)

    async def update_agent_model(
        self, agent_id: str, model: str,
    ) -> None:
        async with self._connection() as db:
            await _agent_hb.update_agent_model(db, agent_id, model)

    async def list_stale_agents(
        self, timeout_seconds: int = 120,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _agent_hb.list_stale_agents(db, timeout_seconds)

    # --- ExecutionSlot CRUD (Phase 10) ---

    async def create_execution_slot(self, slot) -> dict:
        async with self._connection() as db:
            return await _parallel.create_execution_slot(db, slot)

    async def get_execution_slots(
        self, agent_id: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _parallel.get_execution_slots(
                db, agent_id=agent_id, status=status)

    async def update_slot_status(
        self, task_id: str, status: str,
    ) -> None:
        async with self._connection() as db:
            await _parallel.update_slot_status(db, task_id, status)

    async def delete_execution_slot(self, task_id: str) -> None:
        async with self._connection() as db:
            await _parallel.delete_execution_slot(db, task_id)

    # --- ResourceLock CRUD (Phase 10) ---

    async def acquire_resource_lock(self, lock) -> dict:
        async with self._connection() as db:
            return await _parallel.acquire_resource_lock(db, lock)

    async def get_resource_lock(
        self, resource_path: str,
    ) -> dict | None:
        async with self._connection() as db:
            return await _parallel.get_resource_lock(db, resource_path)

    async def get_locks_by_task(self, task_id: str) -> list[dict]:
        async with self._connection() as db:
            return await _parallel.get_locks_by_task(db, task_id)

    async def add_waiting_task(
        self, resource_path: str, task_id: str,
    ) -> None:
        async with self._connection() as db:
            await _parallel.add_waiting_task(db, resource_path, task_id)

    async def release_resource_lock(
        self, resource_path: str,
    ) -> None:
        async with self._connection() as db:
            await _parallel.release_resource_lock(db, resource_path)

    async def release_all_locks_for_task(
        self, task_id: str,
    ) -> None:
        async with self._connection() as db:
            await _parallel.release_all_locks_for_task(db, task_id)

    # --- RBAC CRUD (Phase 10.2) ---

    async def get_role(self, name: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _rbac.get_role(db, name)

    async def list_roles(self) -> list[dict]:
        async with self._connection() as db:
            return await _rbac.list_roles(db)

    async def create_rbac_token(
        self, principal_id: str, role: str, token_hash: str,
        token_id: str, scopes: list[str] | None = None,
        expires_at: Optional[str] = None, tenant_id: str = "default",
    ) -> dict:
        async with self._connection() as db:
            return await _rbac.create_token(
                db, principal_id, role, token_hash, token_id,
                scopes=scopes, expires_at=expires_at,
                tenant_id=tenant_id)

    async def get_rbac_token_by_hash(self, token_hash: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _rbac.get_token_by_hash(db, token_hash)

    async def revoke_rbac_token(self, token_id: int) -> None:
        async with self._connection() as db:
            await _rbac.revoke_token(db, token_id)

    async def log_audit(
        self, event_type: str, actor_id: str, action: str,
        resource: Optional[str] = None, actor_role: Optional[str] = None,
        details: Optional[dict] = None, tenant_id: str = "default",
    ) -> int:
        async with self._connection() as db:
            return await _rbac.log_audit(
                db, event_type, actor_id, action,
                resource=resource, actor_role=actor_role,
                details=details, tenant_id=tenant_id)

    async def query_audit(
        self, tenant_id: str = "default",
        actor_id: Optional[str] = None,
        event_type: Optional[str] = None, limit: int = 100,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _rbac.query_audit(
                db, tenant_id=tenant_id, actor_id=actor_id,
                event_type=event_type, limit=limit)

    # --- Token CRUD (Phase 10.2c) ---

    async def save_token(
        self, token_id: str, token_hash: str,
        principal_id: str, role: str,
        scopes: list[str] | None = None,
        tenant_id: str = "default",
        expires_at: Optional[str] = None,
    ) -> dict:
        async with self._connection() as db:
            return await _tokens.save_token(
                db, token_id, token_hash, principal_id, role,
                scopes=scopes, tenant_id=tenant_id,
                expires_at=expires_at)

    async def get_token(self, token_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _tokens.get_token(db, token_id)

    async def revoke_token(self, token_id: str) -> bool:
        async with self._connection() as db:
            return await _tokens.revoke_token(db, token_id)

    async def list_tokens(
        self, principal_id: Optional[str] = None,
        include_revoked: bool = False,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _tokens.list_tokens(
                db, principal_id=principal_id,
                include_revoked=include_revoked)

    # --- Session CRUD (Phase 12.5a) ---

    async def create_session(
        self, agent_id: str, project_id: str = "default",
        session_type: str = "task_execution",
        started_at: str | None = None,
        ended_at: str | None = None,
        input_messages: list | None = None,
        output_messages: list | None = None,
        tool_calls: list | None = None,
        errors: list | None = None,
        outcome: str = "success",
        metadata: dict | None = None,
    ) -> dict:
        async with self._connection() as db:
            return await _sessions.create_session(
                db, agent_id, project_id=project_id,
                session_type=session_type,
                started_at=started_at, ended_at=ended_at,
                input_messages=input_messages,
                output_messages=output_messages,
                tool_calls=tool_calls, errors=errors,
                outcome=outcome, metadata=metadata)

    async def get_session(self, sid: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _sessions.get_session(db, sid)

    async def query_sessions(
        self, agent_id: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _sessions.list_sessions(
                db, agent_id=agent_id,
                project_id=project_id,
                limit=limit, offset=offset)

    async def update_session(
        self, sid: str, updates: dict,
    ) -> Optional[dict]:
        """Update fields on a session record."""
        async with self._connection() as db:
            return await _sessions.update_session(db, sid, updates)

    async def add_session_note(
        self, sid: str, author: str,
        content: str, tags: list[str] | None = None,
    ) -> Optional[dict]:
        async with self._connection() as db:
            return await _sessions.add_note(
                db, sid, author, content, tags=tags)

    # --- Artifact CRUD (Phase 12.5a) ---

    async def put_artifact(
        self, project_id: str, key: str,
        value: bytes, content_type: str, created_by: str,
    ) -> dict:
        async with self._connection() as db:
            return await _artifacts.put_artifact(
                db, project_id, key, value,
                content_type, created_by)

    async def get_artifact(
        self, project_id: str, key: str,
    ) -> Optional[dict]:
        async with self._connection() as db:
            return await _artifacts.get_artifact(
                db, project_id, key)

    async def delete_artifact(
        self, project_id: str, key: str,
    ) -> bool:
        async with self._connection() as db:
            return await _artifacts.delete_artifact(
                db, project_id, key)

    async def list_artifacts(
        self, project_id: str,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _artifacts.list_artifacts(
                db, project_id)

    # --- PipelineRun CRUD (Phase 13) ---

    async def create_pipeline_run(
        self, project_id: str, idea: str,
        phase: str = "discussing",
        motion_id: str | None = None,
        graph_id: str | None = None,
    ) -> dict:
        async with self._connection() as db:
            return await _pipelines.create_pipeline_run(
                db, project_id, idea, phase=phase,
                motion_id=motion_id, graph_id=graph_id)

    async def get_pipeline_run(self, run_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _pipelines.get_pipeline_run(db, run_id)

    async def list_pipeline_runs(
        self, project_id: str | None = None,
        phase: str | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _pipelines.list_pipeline_runs(
                db, project_id=project_id, phase=phase,
                limit=limit, offset=offset)

    async def update_pipeline_run(
        self, run_id: str, updates: dict,
    ) -> Optional[dict]:
        async with self._connection() as db:
            return await _pipelines.update_pipeline_run(
                db, run_id, updates)

    async def delete_pipeline_run(self, run_id: str) -> bool:
        async with self._connection() as db:
            return await _pipelines.delete_pipeline_run(db, run_id)

    async def count_pipeline_runs(
        self, project_id: str | None = None,
        phase: str | None = None,
    ) -> int:
        """Count total pipeline runs matching filters."""
        async with self._connection() as db:
            return await _pipelines.count_pipeline_runs(
                db, project_id=project_id, phase=phase)

    # --- Notification CRUD (Phase 13) ---

    async def create_notification(
        self, type: str, title: str, body: str,
        project_id: str, priority: str = "medium",
    ) -> dict:
        async with self._connection() as db:
            return await _notifications.create_notification(
                db, type, title, body,
                project_id=project_id, priority=priority)

    async def get_notification(self, notif_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _notifications.get_notification(db, notif_id)

    async def list_notifications(
        self, project_id: str | None = None,
        unread_only: bool = False,
        priority: str | None = None,
        limit: int = 50, offset: int = 0,
    ) -> list[dict]:
        async with self._connection() as db:
            return await _notifications.list_notifications(
                db, project_id=project_id,
                unread_only=unread_only,
                priority=priority,
                limit=limit, offset=offset)

    async def count_notifications(
        self, project_id: str | None = None,
        unread_only: bool = False,
        priority: str | None = None,
    ) -> tuple[int, int]:
        """Return (total, unread_count) for the given filters."""
        async with self._connection() as db:
            return await _notifications.count_notifications(
                db, project_id=project_id,
                unread_only=unread_only,
                priority=priority)

    async def mark_notification_read(
        self, notif_id: str,
    ) -> Optional[dict]:
        async with self._connection() as db:
            return await _notifications.mark_read(db, notif_id)

    async def mark_all_notifications_read(
        self, project_id: str | None = None,
    ) -> int:
        async with self._connection() as db:
            return await _notifications.mark_all_read(
                db, project_id=project_id)

    # --- Metrics History (Phase 13.3a) ---

    async def query_metrics_history(
        self, func_name: str, range_key: str,
        project_id: str | None = None,
    ) -> dict:
        """Dispatch to the right metrics history query function."""
        from . import metrics_history as _mh
        from . import metrics_history_extra as _mhe
        from . import metrics_history_pipeline as _mhp
        func_map = {
            "query_agent_activity": _mh.query_agent_activity,
            "query_task_throughput": _mh.query_task_throughput,
            "query_discussion_outcomes": _mhe.query_discussion_outcomes,
            "query_pipeline_success_rate": _mhp.query_pipeline_success_rate,
            "query_rate_limit_usage": _mhp.query_rate_limit_usage,
        }
        func = func_map.get(func_name)
        if func is None:
            return {"labels": [], "datasets": []}
        async with self._connection() as db:
            return await func(db, range_key, project_id=project_id)
