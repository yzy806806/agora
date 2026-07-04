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
        from ..agora.storage import motions as db
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
                _write_to_memory(
                    motion_id=motion_id,
                    title=title,
                    rationale=rationale,
                    action_items=action_items,
                )

            logger.info(
                "Agora hook: task %s completed (motion %s, decision=%s)",
                task_id, motion_id, decision,
            )

    # --- Phase 2: Self-drive — trigger planner if project is active ---
    try:
        from ..project_planner import on_task_completed as _planner_hook
        _planner_hook(task_id, board=board, assignee=assignee,
                      run_id=run_id, summary=summary)
    except Exception as exc:
        logger.debug("Self-drive planner hook skipped: %s", exc)


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
    """Write the discussion outcome to Hermes MEMORY.md."""
    try:
        from tools.memory_tool import MemoryStore
    except ImportError:
        return

    try:
        store = MemoryStore()
        store.load_from_disk()

        items_str = ""
        if action_items:
            short_items = [ai[:80] for ai in action_items[:3]]
            items_str = " | " + " ; ".join(short_items)

        entry = f"Agora decision ({motion_id}): {title} → {rationale[:120]}{items_str}"
        if len(entry) > 250:
            entry = entry[:247] + "..."

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
            from ..agora.storage import motions as db
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
                from ..agora.storage import motions as db
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
                logger.info(
                    "kanban_task_blocked: created motion %s for blocked task %s",
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
