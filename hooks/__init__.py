"""Agora hooks — deeper Hermes integration via lifecycle callbacks.

Hooks registered:
  - kanban_task_completed  — when a worker finishes a task:
    1. Write the discussion result back as a comment on the task.
    2. Write a concise memory entry for adopted decisions.
    3. **Self-drive**: if the task belongs to an active Agora project and
       no more pending tasks remain, spawn a planner agent to decide the
       next development phase (raise a new motion → new tasks → loop).
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def register_hooks(ctx: Any) -> None:
    """Register Agora's lifecycle hooks with the Hermes plugin manager."""
    ctx.register_hook("kanban_task_completed", _on_task_completed)
    logger.info("Agora hook registered: kanban_task_completed (with self-drive)")


def _on_task_completed(
    task_id: str,
    board: str | None = None,
    assignee: str | None = None,
    run_id: int | None = None,
    summary: str | None = None,
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
                      run_id=run_id, summary=summary,
                      profile_name=profile_name)
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
