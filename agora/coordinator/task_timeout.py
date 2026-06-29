"""Task timeout checker — Phase 19.

Background task that periodically checks for task assignments
that haven't been acknowledged within the timeout window and
reassigns them to different agents.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def check_task_timeouts(
    storage: Any,
    interval_seconds: int = 60,
    timeout_minutes: int = 10,
) -> None:
    """Periodically check for timed-out task assignments and reassign.

    Runs as a background task in the Agora coordinator event loop.

    Args:
        storage: Storage instance for DB access.
        interval_seconds: How often to check (default 60s).
        timeout_minutes: How long to wait for ACK before reassigning (default 10min).
    """
    logger.info(
        "Task timeout checker started (interval=%ds, timeout=%dm)",
        interval_seconds, timeout_minutes,
    )

    while True:
        try:
            await asyncio.sleep(interval_seconds)

            async with storage._connection() as db:
                from .storage.pending_notifications import get_expired_assignments, mark_notification_delivered

                expired = await get_expired_assignments(
                    db, storage.dialect, timeout_minutes=timeout_minutes,
                )

                if not expired:
                    continue

                logger.warning(
                    "Found %d expired task assignment(s) — reassigning",
                    len(expired),
                )

                for entry in expired:
                    notif_id = entry["notif_id"]
                    old_agent = entry["agent_id"]
                    payload = entry["payload"]
                    task_id = payload.get("task_id", "unknown")

                    logger.info(
                        "Task %s timed out for agent %s, attempting reassign",
                        task_id, old_agent,
                    )

                    # Mark the notification as expired
                    await mark_notification_delivered(db, storage.dialect, notif_id)

                    # Try to reassign the task
                    try:
                        from .task_assign import reassign_task
                        new_agent = await reassign_task(
                            task_id, storage, hub=None,
                        )
                        if new_agent:
                            logger.info(
                                "Reassigned task %s from %s to %s",
                                task_id, old_agent, new_agent,
                            )
                        else:
                            logger.warning(
                                "No alternative agent available for task %s",
                                task_id,
                            )
                    except Exception as exc:
                        logger.error(
                            "Failed to reassign task %s: %s",
                            task_id, exc, exc_info=True,
                        )

        except asyncio.CancelledError:
            logger.info("Task timeout checker stopped")
            break
        except Exception as exc:
            logger.error(
                "Task timeout checker error: %s",
                exc, exc_info=True,
            )
