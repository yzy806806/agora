"""LLM-driven discussion driver — makes architect/developer/reviewer speak automatically.

Replaces the passive wait_for_result() polling loop with an active LLM-driven
multi-round discussion.  Each round, every participant role generates a response
via the LLM, which is stored as a discussion message and broadcast via the event bus.

After max_rounds or early consensus, the discussion is closed with a summary
and a simple-majority vote on action items.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .llm_driver import LLMClient, LLMConfig
from .role_prompts import ROLE_PROMPTS, SUMMARIZER_PROMPT
from .storage import Storage
from .event_bus import publish

logger = logging.getLogger(__name__)

# Default participant roles in speaking order
DEFAULT_ROLES: list[str] = ["architect", "developer", "reviewer"]


@dataclass
class DiscussionSummary:
    """Structured summary of an LLM-driven discussion."""

    motion_id: str
    decision: str  # adopted / rejected / no_consensus
    summary: str = ""
    consensus_points: list[str] = field(default_factory=list)
    disagreements: list[str] = field(default_factory=list)
    action_items: list[dict[str, str]] = field(default_factory=list)
    confidence: float = 0.0
    unresolved: list[str] = field(default_factory=list)
    rounds_completed: int = 0


class DiscussionLLMDriver:
    """Drive a multi-round LLM discussion for a motion.

    Usage::

        driver = DiscussionLLMDriver(llm_config=LLMConfig.from_env())
        result = await driver.drive_discussion(motion_id, storage)
    """

    def __init__(
        self,
        llm_config: LLMConfig | None = None,
        max_rounds: int = 3,
        roles: list[str] | None = None,
        consensus_threshold: float = 0.7,
    ) -> None:
        self.llm_config = llm_config or LLMConfig.from_env()
        self.max_rounds = max_rounds
        self.roles = roles or DEFAULT_ROLES
        self.consensus_threshold = consensus_threshold
        self._llm: LLMClient | None = None

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(self.llm_config)
        return self._llm

    async def drive_discussion(
        self,
        motion_id: str,
        storage: Storage,
    ) -> DiscussionSummary:
        """Run the full LLM-driven discussion for a motion.

        For each round:
          1. Fetch motion details and existing messages
          2. For each role, build context + call LLM → store message
          3. After all roles speak, check for early consensus
        After max_rounds, generate a summary and close the discussion.

        Args:
            motion_id: The motion to discuss.
            storage: Storage backend for reading/writing messages.

        Returns:
            DiscussionSummary with the final outcome.
        """
        llm = self._get_llm()

        # Fetch motion details
        motion = await storage.get_motion(motion_id)
        if motion is None:
            raise ValueError(f"Motion {motion_id} not found")

        motion_title = motion.get("title", "")
        motion_desc = motion.get("description", "")
        current_round = motion.get("current_round", 0)

        logger.info(
            "Starting LLM-driven discussion for motion=%s title='%s' rounds=%d",
            motion_id, motion_title, self.max_rounds,
        )

        for round_num in range(1, self.max_rounds + 1):
            logger.info(
                "Discussion round %d/%d for motion=%s",
                round_num, self.max_rounds, motion_id,
            )

            # Increment round in storage
            try:
                await storage.increment_round(motion_id)
            except Exception:
                logger.debug("increment_round failed (may already be at round %d)", round_num)

            # Each role speaks in order
            for role in self.roles:
                try:
                    await self._role_speak(
                        llm=llm,
                        motion_id=motion_id,
                        role=role,
                        round_num=round_num,
                        motion_title=motion_title,
                        motion_desc=motion_desc,
                        storage=storage,
                    )
                except Exception as exc:
                    logger.error(
                        "Role %s failed to speak in round %d: %s",
                        role, round_num, exc,
                    )
                    # Store a fallback message so the discussion continues
                    await storage.add_message(
                        motion_id=motion_id,
                        agent_id=role,
                        round_num=round_num,
                        stance="neutral",
                        content=f"[Error generating response: {exc}]",
                    )

            # Check for early consensus after each round
            if round_num < self.max_rounds:
                consensus = await self._check_consensus(
                    llm, motion_id, storage,
                )
                if consensus and consensus.get("confidence", 0) >= self.consensus_threshold:
                    logger.info(
                        "Early consensus reached at round %d (confidence=%.2f)",
                        round_num, consensus["confidence"],
                    )
                    return await self._finalize(
                        llm, motion_id, storage, round_num,
                        decision="adopted",
                    )

        # Max rounds reached — finalize with summary
        return await self._finalize(
            llm, motion_id, storage, self.max_rounds,
        )

    async def _role_speak(
        self,
        llm: LLMClient,
        motion_id: str,
        role: str,
        round_num: int,
        motion_title: str,
        motion_desc: str,
        storage: Storage,
    ) -> None:
        """Have a single role generate and store a discussion message."""
        # Build conversation history from existing messages
        history = await self._build_message_history(motion_id, storage)

        # Build the user prompt for this round
        user_prompt = self._build_user_prompt(
            role=role,
            round_num=round_num,
            motion_title=motion_title,
            motion_desc=motion_desc,
        )

        messages: list[dict[str, str]] = history + [
            {"role": "user", "content": user_prompt},
        ]

        # Get the system prompt for this role
        system_prompt = ROLE_PROMPTS.get(role, ROLE_PROMPTS["architect"])

        # Call LLM
        response = await llm.chat(
            role=role,
            system_prompt=system_prompt,
            messages=messages,
        )

        # Determine stance (simple heuristic from response)
        stance = self._infer_stance(response)

        # Store the message
        msg_id = await storage.add_message(
            motion_id=motion_id,
            agent_id=role,
            round_num=round_num,
            stance=stance,
            content=response,
        )

        # Publish DISCUSSION_MESSAGE event
        try:
            await publish("DISCUSSION_MESSAGE", {
                "conversation_id": motion_id,
                "sender_id": role,
                "message": response,
                "round": round_num,
                "stance": stance,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, channel="discussions")
        except Exception as exc:
            logger.debug("Event bus publish failed: %s", exc)

        logger.info(
            "Role %s spoke in round %d (msg_id=%s stance=%s len=%d)",
            role, round_num, msg_id, stance, len(response),
        )

    async def _build_message_history(
        self,
        motion_id: str,
        storage: Storage,
    ) -> list[dict[str, str]]:
        """Build LLM message history from stored discussion messages."""
        stored = await storage.get_messages(motion_id)
        history: list[dict[str, str]] = []
        for msg in stored:
            agent_id = msg.get("agent_id", "unknown")
            content = msg.get("content", "")
            # Map agent_id to LLM role
            if agent_id in DEFAULT_ROLES:
                history.append({"role": "assistant", "content": f"[{agent_id}]: {content}"})
            else:
                history.append({"role": "user", "content": f"[{agent_id}]: {content}"})
        return history

    def _build_user_prompt(
        self,
        role: str,
        round_num: int,
        motion_title: str,
        motion_desc: str,
    ) -> str:
        """Build the user prompt that triggers the role's response."""
        parts = [
            f"Motion: {motion_title}",
        ]
        if motion_desc:
            parts.append(f"Description: {motion_desc}")
        parts.append(f"Round: {round_num}")
        parts.append(
            f"Please provide your perspective as the {role} on this motion. "
            f"Respond with your analysis and recommendations."
        )
        return "\n".join(parts)

    def _infer_stance(self, response: str) -> str:
        """Simple heuristic to infer stance from response text."""
        lower = response.lower()
        support_signals = ["agree", "support", "recommend", "endorse", "approve", "yes"]
        oppose_signals = ["disagree", "oppose", "reject", "concern", "risk", "no", "should not"]

        support_count = sum(1 for s in support_signals if s in lower)
        oppose_count = sum(1 for s in oppose_signals if s in lower)

        if support_count > oppose_count + 1:
            return "support"
        elif oppose_count > support_count + 1:
            return "oppose"
        return "neutral"

    async def _check_consensus(
        self,
        llm: LLMClient,
        motion_id: str,
        storage: Storage,
    ) -> dict[str, Any] | None:
        """Use the LLM to check if consensus has been reached."""
        messages = await storage.get_messages(motion_id)
        if len(messages) < len(self.roles):
            return None  # Not enough messages yet

        # Build a summary of all messages for the LLM
        discussion_text = "\n".join(
            f"[{m.get('agent_id', '?')} round {m.get('round_num', '?')}]: "
            f"{m.get('content', '')}"
            for m in messages
        )

        try:
            response = await llm.chat(
                role="architect",  # Use default model for meta-tasks
                system_prompt=(
                    "You are a consensus checker. Analyze the discussion and determine "
                    "if the participants have reached consensus. Respond with JSON only: "
                    '{"consensus": true/false, "confidence": 0.0-1.0, "reason": "..."}'
                ),
                messages=[{"role": "user", "content": discussion_text}],
            )
            # Parse JSON from response
            # Handle markdown code blocks
            text = response.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

            result = json.loads(text)
            return result
        except (json.JSONDecodeError, Exception) as exc:
            logger.debug("Consensus check failed: %s", exc)
            return None

    async def _finalize(
        self,
        llm: LLMClient,
        motion_id: str,
        storage: Storage,
        rounds_completed: int,
        decision: str = "",
    ) -> DiscussionSummary:
        """Generate a final summary and close the discussion."""
        messages = await storage.get_messages(motion_id)

        # Build discussion text for summarization
        discussion_text = "\n".join(
            f"[{m.get('agent_id', '?')} round {m.get('round_num', '?')} "
            f"stance={m.get('stance', '?')}]: {m.get('content', '')}"
            for m in messages
        )

        # Generate summary via LLM
        summary_data: dict[str, Any] = {}
        try:
            summary_response = await llm.chat(
                role="architect",  # Use default model for summarization
                system_prompt=SUMMARIZER_PROMPT,
                messages=[{"role": "user", "content": discussion_text}],
            )
            text = summary_response.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            summary_data = json.loads(text)
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Summary generation failed: %s", exc)
            summary_data = {
                "summary": f"Discussion completed after {rounds_completed} rounds.",
                "consensus_points": [],
                "disagreements": [],
                "action_items": [],
                "confidence": 0.5,
                "unresolved": [],
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

        # Conduct a simple-majority vote on action items
        action_items = summary_data.get("action_items", [])
        if action_items and decision == "adopted":
            action_items = await self._vote_on_action_items(
                llm, action_items, discussion_text,
            )

        # Update motion status in storage
        try:
            await storage.update_motion_status(
                motion_id,
                "closed",
                decision=decision,
                rationale=summary_data.get("summary", ""),
                action_items=[
                    ai.get("item", str(ai)) if isinstance(ai, dict) else str(ai)
                    for ai in action_items
                ],
            )
        except Exception as exc:
            logger.warning("Failed to update motion status: %s", exc)

        # Publish final event
        try:
            await publish("DISCUSSION_MESSAGE", {
                "conversation_id": motion_id,
                "sender_id": "system",
                "message": f"Discussion closed: {decision}. "
                           f"Summary: {summary_data.get('summary', '')}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, channel="discussions")
        except Exception as exc:
            logger.debug("Final event publish failed: %s", exc)

        logger.info(
            "Discussion finalized: motion=%s decision=%s confidence=%.2f rounds=%d",
            motion_id, decision, summary_data.get("confidence", 0), rounds_completed,
        )

        return DiscussionSummary(
            motion_id=motion_id,
            decision=decision,
            summary=summary_data.get("summary", ""),
            consensus_points=summary_data.get("consensus_points", []),
            disagreements=summary_data.get("disagreements", []),
            action_items=action_items,
            confidence=summary_data.get("confidence", 0.0),
            unresolved=summary_data.get("unresolved", []),
            rounds_completed=rounds_completed,
        )

    async def _vote_on_action_items(
        self,
        llm: LLMClient,
        action_items: list[Any],
        discussion_text: str,
    ) -> list[dict[str, str]]:
        """Simple majority vote: each role votes yes/no on each action item."""
        items_text = "\n".join(
            f"{i+1}. {ai.get('item', str(ai)) if isinstance(ai, dict) else str(ai)}"
            for i, ai in enumerate(action_items)
        )

        approved_items: list[dict[str, str]] = []
        for i, ai in enumerate(action_items):
            item_str = ai.get("item", str(ai)) if isinstance(ai, dict) else str(ai)
            owner = ai.get("owner", "unassigned") if isinstance(ai, dict) else "unassigned"

            yes_votes = 0
            for role in self.roles:
                try:
                    vote_response = await llm.chat(
                        role=role,
                        system_prompt=ROLE_PROMPTS.get(role, ROLE_PROMPTS["architect"]),
                        messages=[
                            {"role": "user", "content": discussion_text[:2000]},
                            {"role": "user", "content": (
                                f"Vote on this action item: {item_str}\n"
                                "Respond with ONLY 'yes' or 'no' and a brief reason."
                            )},
                        ],
                    )
                    if "yes" in vote_response.lower()[:20]:
                        yes_votes += 1
                except Exception as exc:
                    logger.debug("Vote failed for role=%s item=%d: %s", role, i, exc)
                    # Abstain on error — count as no
                    pass

            # Simple majority: > half of roles
            if yes_votes > len(self.roles) // 2:
                approved_items.append({"item": item_str, "owner": owner})

        return approved_items

    async def close(self) -> None:
        """Clean up resources."""
        if self._llm is not None:
            await self._llm.close()
            self._llm = None
