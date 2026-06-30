"""LLM-driven discussion driver — the heart of Agora.

Uses ctx.llm (Hermes plugin LLM facade) to simulate a multi-role
discussion. Each round, every participant role generates a response
via the LLM. After max_rounds or early consensus, the discussion is
closed with a structured summary and action items.

Action items are dispatched to the Hermes kanban board for execution
by worker profiles.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from ..storage import motions as db
from .roles import (
    CONSENSUS_CHECKER_PROMPT,
    DEFAULT_ROLES,
    ROLE_PROMPTS,
    SUMMARIZER_PROMPT,
)

logger = logging.getLogger(__name__)


@dataclass
class DiscussionResult:
    """Outcome of a completed discussion."""

    motion_id: str
    decision: str  # adopted / rejected / no_consensus
    summary: str = ""
    consensus_points: list[str] = field(default_factory=list)
    disagreements: list[str] = field(default_factory=list)
    action_items: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    unresolved: list[str] = field(default_factory=list)
    rounds_completed: int = 0
    created_tasks: list[str] = field(default_factory=list)  # kanban task IDs


class DiscussionDriver:
    """Drive a multi-round LLM discussion for a motion.

    Usage::

        driver = DiscussionDriver(ctx)
        result = await driver.run(motion_id)
    """

    def __init__(
        self,
        ctx: Any,  # PluginContext
        max_rounds: int = 3,
        consensus_threshold: float = 0.7,
        auto_create_tasks: bool = True,
    ) -> None:
        self.ctx = ctx
        self.max_rounds = max_rounds
        self.consensus_threshold = consensus_threshold
        self.auto_create_tasks = auto_create_tasks

    async def run(self, motion_id: str) -> DiscussionResult:
        """Run the full discussion for a motion.

        This is the main entry point. It:
        1. Fetches the motion
        2. Runs N rounds of multi-role discussion via ctx.llm
        3. Checks for early consensus
        4. Generates a structured summary
        5. Closes the motion
        6. Creates kanban tasks from action items
        7. Unblocks source task if blocking=True
        """
        motion = db.get_motion(motion_id)
        if motion is None:
            raise ValueError(f"Motion {motion_id} not found")

        title = motion["title"]
        description = motion.get("description", "")
        participants = motion.get("participants") or DEFAULT_ROLES
        max_rounds = motion.get("max_rounds", self.max_rounds)

        logger.info(
            "Starting discussion: motion=%s title='%s' roles=%s rounds=%d",
            motion_id, title, participants, max_rounds,
        )

        for round_num in range(1, max_rounds + 1):
            db.increment_round(motion_id)
            logger.info("Round %d/%d for motion=%s", round_num, max_rounds, motion_id)

            # Each role speaks in order
            for role in participants:
                try:
                    await self._role_speak(
                        motion_id=motion_id,
                        role=role,
                        round_num=round_num,
                        title=title,
                        description=description,
                        participants=participants,
                    )
                except Exception as exc:
                    logger.error("Role %s failed in round %d: %s", role, round_num, exc)
                    db.add_message(
                        motion_id=motion_id,
                        role=role,
                        round_num=round_num,
                        stance="neutral",
                        content=f"[Error generating response: {exc}]",
                    )

            # Check for early consensus (skip on last round)
            if round_num < max_rounds:
                consensus = await self._check_consensus(motion_id)
                if consensus and consensus.get("confidence", 0) >= self.consensus_threshold:
                    logger.info(
                        "Early consensus at round %d (confidence=%.2f)",
                        round_num, consensus["confidence"],
                    )
                    return await self._finalize(motion_id, round_num, decision="adopted")

        # Max rounds reached
        return await self._finalize(motion_id, max_rounds)

    async def _role_speak(
        self,
        motion_id: str,
        role: str,
        round_num: int,
        title: str,
        description: str,
        participants: list[str],
    ) -> None:
        """Have a single role generate and store a discussion message."""
        # Build conversation history
        history = self._build_history(motion_id)

        # Build the user prompt
        user_prompt = self._build_prompt(
            role=role,
            round_num=round_num,
            title=title,
            description=description,
            participants=participants,
        )

        messages = history + [{"role": "user", "content": user_prompt}]

        # Get the system prompt for this role
        system_prompt = ROLE_PROMPTS.get(role, ROLE_PROMPTS["architect"])

        # Call LLM via ctx.llm
        result = self.ctx.llm.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                *messages,
            ],
            temperature=0.4,
            max_tokens=1024,
            purpose=f"agora-discussion-{role}-r{round_num}",
        )

        response_text = result.text.strip()
        stance = self._infer_stance(response_text)

        # Store the message
        db.add_message(
            motion_id=motion_id,
            role=role,
            round_num=round_num,
            stance=stance,
            content=response_text,
        )

        logger.info(
            "Role %s spoke in round %d (stance=%s len=%d)",
            role, round_num, stance, len(response_text),
        )

    def _build_history(self, motion_id: str) -> list[dict[str, str]]:
        """Build LLM message history from stored discussion messages."""
        stored = db.get_messages(motion_id)
        history: list[dict[str, str]] = []
        for msg in stored:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            round_num = msg.get("round_num", 1)
            history.append({
                "role": "user",
                "content": f"[{role} (Round {round_num})]: {content}",
            })
        return history

    def _build_prompt(
        self,
        role: str,
        round_num: int,
        title: str,
        description: str,
        participants: list[str],
    ) -> str:
        """Build the prompt that triggers the role's response."""
        parts = [f"## Motion: {title}"]
        if description:
            parts.append(f"## Description\n{description}")
        parts.append(f"## Round {round_num}")
        if round_num == 1:
            parts.append(
                f"You are the **{role}**. This is the opening round. "
                f"Provide your initial perspective on this motion."
            )
        else:
            parts.append(
                f"You are the **{role}**. Review the previous rounds above. "
                f"Build on points you agree with, counter those you disagree with, "
                f"and refine your position."
            )
        return "\n\n".join(parts)

    def _infer_stance(self, text: str) -> str:
        """Simple heuristic to infer stance from response text."""
        lower = text.lower()
        support = sum(1 for s in ["agree", "support", "recommend", "endorse", "approve"] if s in lower)
        oppose = sum(1 for s in ["disagree", "oppose", "reject", "concern", "risk"] if s in lower)
        if support > oppose + 1:
            return "support"
        elif oppose > support + 1:
            return "oppose"
        return "neutral"

    async def _check_consensus(self, motion_id: str) -> dict | None:
        """Use LLM to check if consensus has been reached."""
        messages = db.get_messages(motion_id)
        if len(messages) < 3:
            return None

        discussion_text = "\n".join(
            f"[{m['role']} R{m['round_num']}]: {m['content'][:500]}"
            for m in messages
        )

        try:
            result = self.ctx.llm.complete(
                messages=[
                    {"role": "system", "content": CONSENSUS_CHECKER_PROMPT},
                    {"role": "user", "content": discussion_text},
                ],
                temperature=0.0,
                max_tokens=256,
                purpose="agora-consensus-check",
            )
            return _parse_json(result.text)
        except Exception as exc:
            logger.debug("Consensus check failed: %s", exc)
            return None

    async def _finalize(
        self,
        motion_id: str,
        rounds_completed: int,
        decision: str = "",
    ) -> DiscussionResult:
        """Generate summary, close motion, create tasks."""
        motion = db.get_motion(motion_id)
        messages = db.get_messages(motion_id)

        discussion_text = "\n".join(
            f"[{m['role']} R{m['round_num']} ({m['stance']})]: {m['content']}"
            for m in messages
        )

        # Generate structured summary via LLM
        summary_data: dict[str, Any] = {}
        try:
            result = self.ctx.llm.complete(
                messages=[
                    {"role": "system", "content": SUMMARIZER_PROMPT},
                    {"role": "user", "content": discussion_text},
                ],
                temperature=0.2,
                max_tokens=1024,
                purpose="agora-summary",
            )
            summary_data = _parse_json(result.text) or {}
        except Exception as exc:
            logger.warning("Summary generation failed: %s", exc)
            summary_data = {
                "summary": f"Discussion completed after {rounds_completed} rounds.",
                "action_items": [],
                "confidence": 0.5,
            }

        # Determine final decision
        if not decision:
            confidence = summary_data.get("confidence", 0.0)
            if confidence >= self.consensus_threshold:
                decision = "adopted"
            elif confidence >= 0.4:
                decision = "no_consensus"
            else:
                decision = "rejected"

        # Extract action items
        action_items = summary_data.get("action_items", [])
        action_item_strings = [
            ai.get("item", str(ai)) if isinstance(ai, dict) else str(ai)
            for ai in action_items
        ]

        # Close the motion
        db.update_motion_status(
            motion_id,
            status="closed",
            decision=decision,
            rationale=summary_data.get("summary", ""),
            action_items=action_item_strings,
        )

        # Create kanban tasks from action items
        created_tasks: list[str] = []
        if self.auto_create_tasks and action_items:
            created_tasks = self._create_kanban_tasks(
                motion_id=motion_id,
                title=motion["title"],
                action_items=action_items,
                source_task_id=motion.get("source_task_id"),
            )

        # Unblock source task if blocking
        if motion.get("blocking") and motion.get("source_task_id"):
            self._unblock_source_task(
                motion_id=motion_id,
                source_task_id=motion["source_task_id"],
                decision=decision,
                summary=summary_data.get("summary", ""),
            )

        logger.info(
            "Discussion finalized: motion=%s decision=%s confidence=%.2f tasks=%d",
            motion_id, decision, summary_data.get("confidence", 0), len(created_tasks),
        )

        return DiscussionResult(
            motion_id=motion_id,
            decision=decision,
            summary=summary_data.get("summary", ""),
            consensus_points=summary_data.get("consensus_points", []),
            disagreements=summary_data.get("disagreements", []),
            action_items=action_items,
            confidence=summary_data.get("confidence", 0.0),
            unresolved=summary_data.get("unresolved", []),
            rounds_completed=rounds_completed,
            created_tasks=created_tasks,
        )

    def _create_kanban_tasks(
        self,
        motion_id: str,
        title: str,
        action_items: list[Any],
        source_task_id: str | None = None,
    ) -> list[str]:
        """Create kanban tasks from discussion action items."""
        try:
            from hermes_cli import kanban_db
        except ImportError:
            logger.warning("kanban_db not available — skipping task creation")
            return []

        created: list[str] = []
        conn = kanban_db.connect()
        try:
            for ai in action_items:
                if isinstance(ai, dict):
                    item_title = ai.get("item", str(ai))
                    owner = ai.get("owner", "")
                else:
                    item_title = str(ai)
                    owner = ""

                # Map owner role to kanban assignee (profile name)
                assignee = owner if owner else None

                task_id = kanban_db.create_task(
                    conn,
                    title=item_title[:200],
                    body=(
                        f"From Agora discussion: {title}\n"
                        f"Motion: {motion_id}\n"
                        f"Action item: {item_title}"
                    ),
                    assignee=assignee,
                    workspace_kind="dir",
                    parents=[source_task_id] if source_task_id else [],
                )
                created.append(task_id)
                logger.info("Created kanban task %s for action item: %s", task_id, item_title[:80])
        except Exception as exc:
            logger.error("Failed to create kanban tasks: %s", exc)
        finally:
            conn.close()

        return created

    def _unblock_source_task(
        self,
        motion_id: str,
        source_task_id: str,
        decision: str,
        summary: str,
    ) -> None:
        """Unblock the source kanban task and write discussion result as comment."""
        try:
            from hermes_cli import kanban_db
        except ImportError:
            logger.warning("kanban_db not available — skipping unblock")
            return

        conn = kanban_db.connect()
        try:
            # Write discussion result as a comment
            comment_text = (
                f"[Agora Motion {motion_id}] Discussion completed: {decision}\n"
                f"Summary: {summary}"
            )
            try:
                kanban_db.add_comment(conn, source_task_id, comment_text)
            except Exception:
                logger.debug("add_comment failed (may not exist in this version)")

            # Unblock the task
            try:
                kanban_db.unblock_task(conn, source_task_id)
            except Exception as exc:
                logger.debug("unblock_task failed: %s", exc)

            conn.commit()
            logger.info("Unblocked source task %s after motion %s", source_task_id, motion_id)
        except Exception as exc:
            logger.error("Failed to unblock source task: %s", exc)
        finally:
            conn.close()


def _parse_json(text: str) -> dict | None:
    """Extract and parse JSON from LLM response text."""
    text = text.strip()

    # Strip markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        text = "\n".join(lines)

    # Try to find JSON object in the text
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        text = match.group(0)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
