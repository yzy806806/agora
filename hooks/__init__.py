"""Agora hooks — deeper Hermes integration via lifecycle callbacks.

Hooks registered:
  - kanban_task_completed  — when a worker finishes a task, check if it
    originated from an Agora motion. If so, write the discussion result
    back as a comment on the task and, if the motion was adopted, record
    the decision in Hermes memory for future sessions.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def register_hooks(ctx: Any) -> None:
    """Register Agora's lifecycle hooks with the Hermes plugin manager."""
    # Kanban task completion hook — fires in the WORKER process after
    # kanban_complete() commits. kwargs: task_id, board, assignee,
    # run_id, summary, profile_name.
    ctx.register_hook("kanban_task_completed", _on_task_completed)
    logger.info("Agora hook registered: kanban_task_completed")


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

    When a kanban task created by Agora completes, we:
    1. Look up the originating motion (via source_task_id or task body).
    2. If the motion is closed with decision=adopted, write the
       discussion result as a kanban comment on the completed task.
    3. Write a concise memory entry so future sessions remember the
       decision and its rationale.
    """
    try:
        from ..agora.storage import motions as db
    except ImportError:
        return

    # Find motions that reference this task as their source.
    motion = _find_motion_for_task(task_id, db)
    if motion is None:
        return  # Not an Agora-originated task, nothing to do.

    if motion.get("status") != "closed":
        return  # Discussion still in progress.

    decision = motion.get("decision", "")
    rationale = motion.get("rationale", "")
    action_items = motion.get("action_items", [])
    motion_id = motion["id"]
    title = motion["title"]

    # 1. Write result as a kanban comment on the completed task.
    _write_kanban_comment(
        task_id=task_id,
        motion_id=motion_id,
        title=title,
        decision=decision,
        rationale=rationale,
        action_items=action_items,
    )

    # 2. Write to Hermes memory if the motion was adopted.
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


# ---------------------------------------------------------------------------


def _find_motion_for_task(task_id: str, db_module: Any) -> dict | None:
    """Find a motion whose source_task_id matches the completed task."""
    try:
        # List recent closed motions and match by source_task_id.
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
        logger.debug("kanban_db not available — skipping comment")
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
    """Write the discussion outcome to Hermes MEMORY.md.

    Uses MemoryStore.add() directly — the same path the memory tool uses
    internally. This means the entry appears in MEMORY.md and is injected
    into the system prompt for future sessions.
    """
    try:
        from tools.memory_tool import MemoryStore
    except ImportError:
        logger.debug("MemoryStore not available — skipping memory write")
        return

    try:
        store = MemoryStore()
        store.load_from_disk()

        # Build a concise memory entry — declarative fact, not a log.
        # Keep it short to stay within the char limit.
        items_str = ""
        if action_items:
            # Take at most 3 items, truncated.
            short_items = [ai[:80] for ai in action_items[:3]]
            items_str = " | " + " ; ".join(short_items)

        # Cap total length to ~200 chars to be a good memory citizen.
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
