"""Agora hooks — deeper Hermes integration via lifecycle callbacks.

Hooks registered:
  - kanban_task_completed  — when a worker finishes a task:
    1. Write the discussion result back as a comment on the task.
    2. Write a concise memory entry for adopted decisions.
    3. **Self-drive**: if the task belongs to an active Agora project and
       no more pending tasks remain, spawn a planner agent to decide the
       next development phase (raise a new motion → new tasks → loop).

  - kanban_task_claimed — fires in the dispatcher BEFORE the worker spawns:
    1. Log the claim (task_id, assignee, board).
    2. If the task belongs to an Agora project, record the claim time.
    3. If the task has a source motion, inject the motion decision as a
       comment on the task body.

  - kanban_task_blocked — fires in the worker process when a task is blocked:
    1. Log the block (task_id, reason, board).
    2. If the reason mentions 'design decision' or 'motion', auto-trigger
       a discussion by creating a new motion.
    3. Otherwise, log it for the leader to handle on next heartbeat.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def register_hooks(ctx: Any) -> None:
    """Register Agora's lifecycle hooks with the Hermes plugin manager."""
    ctx.register_hook("kanban_task_completed", _on_task_completed)
    ctx.register_hook("kanban_task_claimed", _on_task_claimed)
    ctx.register_hook("kanban_task_blocked", _on_task_blocked)
    logger.info(
        "Agora hooks registered: kanban_task_completed, "
        "kanban_task_claimed, kanban_task_blocked"
    )


def _on_task_completed(
    task_id: str,
    board: str | None = None,
    assignee: str | None = None,
    run_id: int | None = None,
    summary: str | None = None,
    # Hermes v0.18 hooks receive kwargs, not a ctx object.  profile_name is
    # passed by the kanban dispatcher.  If a future Hermes version provides
    # ctx to hooks, switch to ctx.profile_name here for consistency with
    # tool handlers.
    profile_name: str = "default",
    **_kwargs: Any,
) -> None:
    """Callback for kanban_task_completed.

    1. If the task originated from an Agora motion, write the discussion
       result as a kanban comment and record in memory.
    2. **Self-drive**: check if this task belongs to an active Agora-managed
       project. If so and no pending tasks remain, spawn a planner.
    """
    # --- Phase 1: Existing behavior — write motion result to task + memory ---
    try:
        from agora.storage import motions as db
    except ImportError:
        db = None

    if db is not None:
        motion = _find_motion_for_task(task_id, db)
        if motion is not None and motion.get("status") == "closed":
            decision = motion.get("decision", "")
            rationale = motion.get("rationale", "")
            action_items = motion.get("action_items", [])
            motion_id = motion["id"]
            title = motion["title"]

            _write_kanban_comment(
                task_id=task_id,
                motion_id=motion_id,
                title=title,
                decision=decision,
                rationale=rationale,
                action_items=action_items,
            )

            if decision == "adopted":
                # Only write motion decisions to the LEADER's memory.
                # Workers don't need to remember every team decision —
                # they should record their own technical experience instead.
                # Motion records are session-level info that goes stale;
                # Hermes guidance says "if it'll be stale in a week, don't
                # put it in memory."
                if profile_name and profile_name != "default":
                    # Check if this profile is a leader
                    try:
                        from agora.worker_manager import get_worker
                        worker = get_worker(profile_name)
                        if worker and worker.get("is_leader"):
                            _write_to_memory(
                                motion_id=motion_id,
                                title=title,
                                rationale=rationale,
                                action_items=action_items,
                            )
                    except Exception:
                        pass

            logger.info(
                "Agora hook: task %s completed (motion %s, decision=%s)",
                task_id, motion_id, decision,
            )

    # --- Phase 2: Self-drive — trigger planner if project is active ---
    try:
        from project_planner import on_task_completed as _planner_hook
        _planner_hook(task_id, board=board, assignee=assignee,
                      run_id=run_id, summary=summary)
    except Exception as exc:
        logger.debug("Self-drive planner hook skipped: %s", exc)

    # --- Phase 3: Skill creation nudge for complex tasks ---
    # If a task had retries or took a long time, the worker likely solved
    # a non-trivial problem worth saving as a skill. Write a kanban comment
    # prompting the worker to save their workflow.
    try:
        _maybe_nudge_skill_creation(task_id, profile_name)
    except Exception as exc:
        logger.debug("Skill nudge skipped: %s", exc)


def _maybe_nudge_skill_creation(task_id: str, profile_name: str) -> None:
    """Write a skill-creation nudge as a kanban comment on complex tasks.

    A task is "complex" if it had >1 run (retries) or took >30 minutes.
    The nudge is a kanban comment — it shows up in the worker's next
    task view and in the dashboard, but doesn't pollute memory.
    """
    try:
        from hermes_cli import kanban_db
        conn = kanban_db.connect()
        try:
            task = kanban_db.get_task(conn, task_id)
            if not task:
                return

            # Count runs for this task
            runs = conn.execute(
                "SELECT COUNT(*) as n FROM task_runs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            run_count = runs["n"] if runs else 0

            # Check duration
            duration_s = 0
            if task.started_at and task.completed_at:
                duration_s = task.completed_at - task.started_at

            is_complex = run_count > 1 or duration_s > 1800  # >1 run or >30min

            if not is_complex:
                return

            # Write a nudge comment
            reasons = []
            if run_count > 1:
                reasons.append(f"{run_count} attempts")
            if duration_s > 1800:
                reasons.append(f"{duration_s // 60}min duration")

            nudge = (
                f"💡 This task was complex ({', '.join(reasons)}). "
                f"If you discovered a reusable workflow or solved a tricky "
                f"problem, consider saving it as a skill with "
                f"`skill_manage(action='create', name='...', content='...')`. "
                f"Skills persist across projects and help future you."
            )

            kanban_db.add_comment(conn, task_id, nudge)
            conn.commit()
            logger.info(
                "Skill nudge written for task %s (%s, profile=%s)",
                task_id, ", ".join(reasons), profile_name,
            )
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("Skill nudge failed for task %s: %s", task_id, exc)


# ---------------------------------------------------------------------------
# Motion → task comment + memory (existing behavior, unchanged)
# ---------------------------------------------------------------------------


def _find_motion_for_task(task_id: str, db_module: Any) -> dict | None:
    """Find a motion whose source_task_id matches the completed task."""
    try:
        motions = db_module.list_motions(status_filter="all", limit=100)
        for m in motions:
            if m.get("source_task_id") == task_id:
                return m
    except Exception as exc:
        logger.debug("Failed to find motion for task %s: %s", task_id, exc)
    return None


def _write_kanban_comment(
    task_id: str,
    motion_id: str,
    title: str,
    decision: str,
    rationale: str,
    action_items: list[str],
) -> None:
    """Append the Agora discussion result as a comment on the kanban task."""
    try:
        from hermes_cli import kanban_db
    except ImportError:
        return

    comment = (
        f"[Agora Motion {motion_id}] Task completed.\n"
        f"Discussion: {title}\n"
        f"Decision: {decision}\n"
        f"Rationale: {rationale}\n"
    )
    if action_items:
        comment += "Action items:\n"
        for ai in action_items:
            comment += f"  - {ai}\n"

    try:
        conn = kanban_db.connect()
        try:
            kanban_db.add_comment(conn, task_id, comment)
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("Failed to write kanban comment for task %s: %s", task_id, exc)


def _write_to_memory(
    motion_id: str,
    title: str,
    rationale: str,
    action_items: list[str],
) -> None:
    """Write a concise motion decision to the LEADER's MEMORY.md only.

    Workers don't receive motion records — they should record their own
    technical experience via the memory tool, not have team decisions
    dumped into their memory by hooks.
    """
    try:
        try:
            from tools.memory_tool import MemoryStore
        except ImportError:
            from hermes_cli.memory_tool import MemoryStore
    except ImportError:
        return

    try:
        store = MemoryStore()
        store.load_from_disk()

        # One concise line — the leader just needs to know what was decided.
        entry = f"Motion {motion_id}: {title[:80]} → {rationale[:100]}"
        if len(entry) > 200:
            entry = entry[:197] + "..."

        result = store.add("memory", entry)
        if result.get("success"):
            logger.info("Agora memory entry written for motion %s", motion_id)
        else:
            logger.debug(
                "Memory write skipped for motion %s: %s",
                motion_id, result.get("error", ""),
            )
    except Exception as exc:
        logger.debug("Failed to write memory for motion %s: %s", motion_id, exc)


# --------------------------------------------------------------------------- #
#  kanban_task_claimed — fires in the dispatcher BEFORE worker spawns          #
# --------------------------------------------------------------------------- #

def _on_task_claimed(
    task_id: str,
    assignee: str | None = None,
    board: str | None = None,
    profile_name: str = "default",
    **_kwargs: Any,
) -> None:
    """Callback for kanban_task_claimed.

    1. Log the claim (task_id, assignee, board).
    2. If the task belongs to an Agora project (tenant field), record claim time.
    3. If the task has a source motion, inject the motion decision as a comment.
    """
    try:
        logger.info(
            "kanban_task_claimed: task=%s assignee=%s board=%s",
            task_id, assignee or "(none)", board or "(none)",
        )

        # Look up the task to check tenant and source motion
        tenant = None
        try:
            from hermes_cli import kanban_db
            conn = kanban_db.connect()
            try:
                task = kanban_db.get_task(conn, task_id)
                if task:
                    tenant = getattr(task, "tenant", None) or task.__dict__.get("tenant")
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("Failed to look up task %s for claim hook: %s", task_id, exc)

        # Check if the task belongs to an Agora project
        is_agora = False
        if tenant:
            try:
                from project_planner import get_project, update_project_agents_md
                proj = get_project(tenant)
                if proj is not None and proj.get("status") == "active":
                    is_agora = True
                    update_project_agents_md(proj["name"])
                    logger.info(
                        "Agora claim: task %s claimed by %s for project %s at %s",
                        task_id, assignee or "(none)", tenant,
                        datetime.now(timezone.utc).isoformat(),
                    )
            except Exception:
                pass

        # If the task has a source motion, inject the motion decision as a comment
        try:
            from agora.storage import motions as db
            motion = _find_motion_for_task(task_id, db)
            if motion is not None and motion.get("status") == "closed":
                decision = motion.get("decision", "")
                rationale = motion.get("rationale", "")
                if decision:
                    comment = (
                        f"[Agora Motion {motion['id']}] Source motion decision: {decision}\n"
                        f"Rationale: {rationale}\n"
                    )
                    try:
                        from hermes_cli import kanban_db
                        conn = kanban_db.connect()
                        try:
                            kanban_db.add_comment(conn, task_id, comment)
                            conn.commit()
                        finally:
                            conn.close()
                    except Exception as exc:
                        logger.debug("Failed to inject motion comment for task %s: %s", task_id, exc)
        except ImportError:
            pass

    except Exception as exc:
        logger.error("kanban_task_claimed hook error for task %s: %s", task_id, exc)


# --------------------------------------------------------------------------- #
#  kanban_task_blocked — fires in the worker when a task gets blocked          #
# --------------------------------------------------------------------------- #

def _on_task_blocked(
    task_id: str,
    reason: str | None = None,
    board: str | None = None,
    profile_name: str = "default",
    **_kwargs: Any,
) -> None:
    """Callback for kanban_task_blocked.

    1. Log the block (task_id, reason, board).
    2. If the reason mentions 'design decision' or 'motion', auto-trigger
       a discussion by creating a new motion.
    3. Otherwise, just log it for the leader to handle on next heartbeat.
    """
    try:
        block_reason = reason or "(no reason)"
        logger.info(
            "kanban_task_blocked: task=%s reason=%s board=%s",
            task_id, block_reason, board or "(none)",
        )

        # Check if the task belongs to an Agora project
        tenant = None
        try:
            from hermes_cli import kanban_db
            conn = kanban_db.connect()
            try:
                task = kanban_db.get_task(conn, task_id)
                if task:
                    tenant = getattr(task, "tenant", None) or task.__dict__.get("tenant")
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("Failed to look up task %s for block hook: %s", task_id, exc)

        is_agora = False
        if tenant:
            try:
                from project_planner import get_project, update_project_agents_md
                proj = get_project(tenant)
                if proj is not None and proj.get("status") == "active":
                    is_agora = True
            except Exception:
                pass

        reason_lower = block_reason.lower()
        should_motion = (
            "design decision" in reason_lower
            or "motion" in reason_lower
        )

        if should_motion and is_agora:
            logger.info(
                "kanban_task_blocked: auto-triggering discussion for task %s "
                "(reason contains 'design decision' or 'motion')",
                task_id,
            )
            try:
                from agora.storage import motions as db
                motion = db.create_motion(
                    title=f"Unblock: {block_reason[:80]}",
                    description=(
                        f"Task {task_id} was blocked with reason: {block_reason}\n\n"
                        f"This motion was auto-triggered by the kanban_task_blocked hook."
                    ),
                    source="agent",
                    source_task_id=task_id,
                    blocking=True,
                )

                # Auto-resolve chair and participants from the project so
                # spawn_discussion_driver has what it needs.  Without this,
                # the motion sits at "discussing" forever — the driver never
                # fires because chair/participants are empty.
                chair = ""
                participants = None
                workdir = ""
                project_name = tenant or ""
                try:
                    from project_planner import get_project, get_heartbeat_member
                    from agora.team_manager import get_team_for_project, get_team
                    proj = get_project(project_name) if project_name else None
                    if proj:
                        workdir = proj.get("workdir", "")
                        chair = get_heartbeat_member(project_name) or ""
                        if proj.get("team"):
                            team = get_team(proj["team"])
                            if team:
                                participants = [w["name"] for w in team.get("workers", [])]
                except Exception as exc:
                    logger.debug("Auto-resolve chair/participants failed: %s", exc)

                if chair and participants:
                    from agora.discussion.agent_spawn import spawn_discussion_driver
                    spawn_status = spawn_discussion_driver(
                        motion_id=motion["id"],
                        chair=chair,
                        participants=participants,
                        workdir=workdir,
                        project_name=project_name,
                    )
                    logger.info(
                        "kanban_task_blocked: created motion %s and spawned discussion "
                        "(chair=%s, participants=%s, status=%s)",
                        motion["id"], chair, participants,
                        spawn_status.get("status"),
                    )
                else:
                    logger.info(
                        "kanban_task_blocked: created motion %s for blocked task %s "
                        "(chair/participants not resolved — will be picked up by leader heartbeat)",
                        motion["id"], task_id,
                    )
            except Exception as exc:
                logger.error(
                    "kanban_task_blocked: failed to create motion for task %s: %s",
                    task_id, exc,
                )
        else:
            logger.info(
                "kanban_task_blocked: task %s logged for leader heartbeat (reason: %s)",
                task_id, block_reason,
            )

    except Exception as exc:
        logger.error("kanban_task_blocked hook error for task %s: %s", task_id, exc)
