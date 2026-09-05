"""Event-driven discussion driver for Agora v2.0.

Replaces the old round-robin ctx.llm.complete approach with:
  - Real agent subprocess spawns (hermes -p <profile> chat -q)
  - Leader as chair: opens, evaluates, redirects, calls votes, summarizes
  - Event-driven flow: Leader picks next speaker dynamically
  - Session isolation: fresh session per heartbeat for attention quality
  - Results stored in motions DB and surfaced via agora tools

Flow:
  1. Chair (Leader) opens → names first speaker + guidance
  2. Speaker speaks (spawn agent with --resume) → message stored
  3. Chair evaluates → continue? vote? close?
  4. Repeat 2-3 until close or max_steps
  5. (Optional) Vote: each participant votes → chair decides
  6. Summary: chair generates action items + closes motion
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agora.storage import motions as db
from agora.utils import get_global_root, parse_json_response
from .agent_spawn import spawn_agent_speak, spawn_chair_speak
from .chair import (
    CHAIR_EVALUATE_PROMPT,
    CHAIR_OPENING_PROMPT,
    CHAIR_SUMMARY_PROMPT,
    CHAIR_VOTE_CALL_PROMPT,
    build_speaker_prompt,
    build_vote_prompt,
    _escape_format,
)

logger = logging.getLogger(__name__)


@dataclass
class DiscussionResult:
    """Outcome of a completed discussion."""
    motion_id: str
    decision: str = ""
    summary: str = ""
    action_items: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    steps_completed: int = 0
    votes: list[dict] = field(default_factory=list)
    created_tasks: list[str] = field(default_factory=list)


class DiscussionDriver:
    """Drive an event-driven discussion using real agent subprocesses.

    Each "speak" is a `hermes -p <profile> --yolo chat -q` subprocess.
    Workers use --resume to keep conversation context across sessions.
    The chair (Leader) makes meta-decisions as a stateless caller.
    """

    def __init__(
        self,
        motion_id: str,
        chair_profile: str,
        participants: list[str],
        workdir: str = "",
        project_name: str = "",
        max_steps: int = 30,
        speak_timeout: int = 3600,
        chair_timeout: int = 3600,
    ) -> None:
        self.motion_id = motion_id
        self.chair_profile = chair_profile
        self.participants = participants
        self.workdir = workdir or None
        self.project_name = project_name
        self.max_steps = max_steps
        # Minimum steps before chair can close — ensures every participant
        # gets at least one chance to speak before the discussion ends.
        self.min_steps = max(3, len(participants))
        self.speak_timeout = speak_timeout
        self.chair_timeout = chair_timeout

    def run(self) -> DiscussionResult:
        """Run the full event-driven discussion.

        Returns a DiscussionResult with the final state.
        """
        motion = db.get_motion(self.motion_id)
        if motion is None:
            raise ValueError(f"Motion {self.motion_id} not found")

        title = motion["title"]
        description = motion.get("description", "")

        # Abort early on empty motions — there is nothing to discuss, and
        # running the loop would just burn worker spawns for no reason.
        if not title or not title.strip():
            logger.warning("Motion %s has empty title, aborting", self.motion_id)
            return self._abort("Motion has empty title — nothing to discuss")

        task_context = self._fetch_task_context(motion.get("source_task_id"))

        logger.info(
            "Starting discussion: motion=%s title='%s' chair=%s participants=%s",
            self.motion_id, title, self.chair_profile, self.participants,
        )

        db.update_motion_state(self.motion_id, "discussing")

        # --- Step 1: Chair opens ---
        opening = self._chair_open(title, description, task_context)
        if opening is None:
            return self._abort("Chair failed to open")

        db.save_discussion_state(
            self.motion_id, "discussing",
            next_speaker=opening.get("next_speaker"),
            last_guidance=opening.get("guidance"),
            last_action="continue",
        )

        # --- Steps 2-N: speak → evaluate → repeat ---
        step = 0
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 3
        # Track how many times the same speaker has spoken consecutively
        # (prevents infinite "your response was truncated, try again" loops)
        last_speaker = None
        same_speaker_count = 0
        MAX_SAME_SPEAKER = 2  # max consecutive turns for the same speaker
        while step < self.max_steps:
            step += 1
            db.increment_step_count(self.motion_id)

            state = db.get_discussion_state(self.motion_id)
            if state is None:
                break

            speaker = state.get("next_speaker")
            guidance = state.get("last_guidance", "")

            if not speaker or speaker not in self.participants:
                # Chair didn't name a valid speaker; try to recover
                speaker = self.participants[step % len(self.participants)]

            # Enforce max consecutive turns for the same speaker
            if speaker == last_speaker:
                same_speaker_count += 1
                if same_speaker_count >= MAX_SAME_SPEAKER:
                    logger.warning(
                        "Speaker %s has spoken %d consecutive times, "
                        "forcing rotation to next participant",
                        speaker, same_speaker_count,
                    )
                    # Rotate to the next participant
                    idx = self.participants.index(speaker)
                    speaker = self.participants[(idx + 1) % len(self.participants)]
                    same_speaker_count = 0
                    # Persist the rotation so the next loop iteration
                    # reads the correct next_speaker from the DB (M5 fix).
                    db.save_discussion_state(
                        self.motion_id, "discussing",
                        next_speaker=speaker,
                    )
            else:
                same_speaker_count = 0
            last_speaker = speaker

            # 2a: Speaker speaks
            logger.info("Step %d: %s speaks", step, speaker)
            reply = self._speaker_speak(
                speaker, title, description, guidance, task_context,
            )
            if not reply:
                reply = f"[{speaker} could not respond]"

            db.add_message(
                motion_id=self.motion_id,
                role=speaker,
                round_num=step,
                stance=self._infer_stance(reply),
                content=reply,
                step_type="speak",
            )

            # Check for human input injected mid-discussion
            human_msgs = self._consume_human_inputs()
            if human_msgs:
                # Human messages are already in the DB; the chair will see them
                logger.info("Human input injected at step %d", step)

            # 2b: Chair evaluates
            action = self._chair_evaluate(title, step)
            if action is None:
                # Chair failed; force close
                logger.warning("Chair evaluation failed at step %d, forcing close", step)
                break

            db.add_message(
                motion_id=self.motion_id,
                role=self.chair_profile,
                round_num=step,
                stance="neutral",
                content=action.get("reason", ""),
                step_type="guidance",
                is_chair=True,
            )

            next_action = action.get("action", "continue")
            if next_action == "close":
                if step < self.min_steps:
                    logger.info(
                        "Chair tried to close at step %d (min_steps=%d) — forcing continue",
                        step, self.min_steps,
                    )
                    continue
                logger.info("Chair called close at step %d", step)
                break
            elif next_action == "vote":
                if step < self.min_steps:
                    logger.info(
                        "Chair tried to vote at step %d (min_steps=%d) — forcing continue",
                        step, self.min_steps,
                    )
                    continue
                logger.info("Chair called vote at step %d", step)
                self._run_voting(title)
                break
            elif next_action == "dispatch":
                # Chair sends a participant to investigate (web search, read
                # code, run tests, etc.) — this is a regular speaker turn but
                # with a specific investigation task instead of opinion.
                investigator = action.get("next_speaker")
                dispatch_task = action.get("dispatch_task", "")
                if investigator and investigator in self.participants:
                    logger.info(
                        "Chair dispatched %s to investigate: %s",
                        investigator, dispatch_task[:100],
                    )
                    db.save_discussion_state(
                        self.motion_id, "investigating",
                        next_speaker=investigator,
                        last_guidance=dispatch_task,
                        last_action="dispatch",
                    )
                    # The investigation is a speaker turn with a task-oriented prompt
                    reply = self._investigator_speak(
                        investigator, title, dispatch_task,
                    )
                    if not reply or reply.startswith("["):
                        # Investigation failed (empty reply or error placeholder)
                        reply = f"[{investigator} could not complete the investigation]"
                        consecutive_failures += 1
                        logger.warning(
                            "Dispatch to %s failed (%d/%d consecutive)",
                            investigator, consecutive_failures,
                            MAX_CONSECUTIVE_FAILURES,
                        )
                        # Clear the worker's session so the next spawn creates a fresh one
                        self._clear_worker_session(investigator)
                        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                            logger.error(
                                "Max consecutive dispatch failures (%d) reached, "
                                "forcing vote",
                                MAX_CONSECUTIVE_FAILURES,
                            )
                            break
                    else:
                        consecutive_failures = 0  # reset on success
                    db.add_message(
                        motion_id=self.motion_id,
                        role=investigator,
                        round_num=step,
                        stance="investigation",
                        content=reply,
                        step_type="dispatch",
                    )
                else:
                    # Invalid investigator — fall through to continue
                    logger.warning(
                        "Chair dispatch target '%s' not in participants, falling through",
                        investigator,
                    )
                    db.save_discussion_state(
                        self.motion_id, "discussing",
                        next_speaker=action.get("next_speaker"),
                        last_guidance=action.get("guidance"),
                        last_action="continue",
                    )
            else:  # continue
                db.save_discussion_state(
                    self.motion_id, "discussing",
                    next_speaker=action.get("next_speaker"),
                    last_guidance=action.get("guidance"),
                    last_action="continue",
                )

        # --- Finalize: summary + task creation ---
        # If we exited the loop due to max_steps (not because the chair called
        # close or vote), force a formal vote before finalizing.
        if step >= self.max_steps and step > 0:
            logger.info("Max steps (%d) reached, forcing vote", self.max_steps)
            self._run_forced_vote(title)

        return self._finalize(title, motion)

    # ------------------------------------------------------------------ #
    #  Chair calls                                                       #
    # ------------------------------------------------------------------ #

    def _chair_open(
        self, title: str, description: str, task_context: str,
    ) -> dict | None:
        """Chair opens the discussion. Retries once on non-JSON response."""
        prompt = CHAIR_OPENING_PROMPT.format(
            title=_escape_format(title),
            description=_escape_format(description),
            participants=", ".join(self.participants),
            task_context=task_context or "(none)",
        )
        result = spawn_chair_speak(
            self.chair_profile, prompt,
            workdir=self.workdir,
            timeout=self.chair_timeout,
        )
        if result.get("error"):
            logger.error("Chair open failed: %s", result["error"])
            return None

        data = parse_json_response(result["reply"])
        if data is None:
            # Retry with a stronger JSON instruction
            logger.warning("Chair open returned non-JSON, retrying: %s", result["reply"][:200])
            retry_prompt = (
                "Your previous response was not valid JSON. "
                "You MUST respond with ONLY a JSON object, no other text.\n\n"
                + prompt
            )
            result = spawn_chair_speak(
                self.chair_profile, retry_prompt,
                workdir=self.workdir,
                timeout=self.chair_timeout,
            )
            if result.get("error"):
                logger.error("Chair open retry failed: %s", result["error"])
                return None
            data = parse_json_response(result["reply"])
            if data is None:
                logger.error("Chair open retry still non-JSON: %s", result["reply"][:200])
                return None

        # Store the opening as a chair message
        db.add_message(
            motion_id=self.motion_id,
            role=self.chair_profile,
            round_num=0,
            stance="neutral",
            content=data.get("opening", ""),
            step_type="opening",
            is_chair=True,
        )
        return data

    def _chair_evaluate(self, title: str, step: int = 0) -> dict | None:
        """Chair evaluates the discussion after each speaker."""
        history = self._build_history()
        prompt = CHAIR_EVALUATE_PROMPT.format(
            title=_escape_format(title),
            participants=", ".join(self.participants),
            discussion_history=history,
        )
        # Warn the chair when approaching the step limit
        if step >= self.max_steps - 3:
            prompt += (
                f"\n⚠️ Discussion is approaching the step limit "
                f"({step}/{self.max_steps}). Please prepare to make a "
                f"final decision or call a vote.\n"
            )
        result = spawn_chair_speak(
            self.chair_profile, prompt,
            workdir=self.workdir,
            timeout=self.chair_timeout,
        )
        if result.get("error"):
            logger.error("Chair evaluate failed: %s", result["error"])
            return None

        data = parse_json_response(result["reply"])
        if data is None:
            # Retry with a stronger JSON instruction
            logger.warning("Chair evaluate returned non-JSON, retrying")
            retry_prompt = (
                "Your previous response was not valid JSON. "
                "You MUST respond with ONLY a JSON object, no other text.\n\n"
                + prompt
            )
            result = spawn_chair_speak(
                self.chair_profile, retry_prompt,
                workdir=self.workdir,
                timeout=self.chair_timeout,
            )
            if result.get("error"):
                logger.error("Chair evaluate retry failed: %s", result["error"])
                return {"action": "close", "reason": "Chair evaluate failed after retry"}
            data = parse_json_response(result["reply"])
            if data is None:
                logger.warning("Chair evaluate retry still non-JSON, defaulting to close")
                return {"action": "close", "reason": "Chair returned non-JSON after retry, forcing close"}
        return data

    # ------------------------------------------------------------------ #
    #  Speaker calls                                                     #
    # ------------------------------------------------------------------ #

    def _speaker_speak(
        self, speaker: str, title: str, description: str,
        guidance: str, task_context: str,
    ) -> str:
        """Spawn a worker agent to speak in the discussion.

        Retries up to 10 times on API 429 / rate-limit errors before giving up.
        """
        max_retries = 10
        for attempt in range(max_retries):
            history = self._build_history()
            prompt = build_speaker_prompt(
                role=speaker,
                title=title,
                description=description,
                discussion_history=history,
                guidance=guidance,
                task_context=task_context,
            )

            # Get the worker's session_id for --resume
            session_id = self._get_worker_session(speaker)

            result = spawn_agent_speak(
                profile_name=speaker,
                prompt=prompt,
                session_id=session_id,
                workdir=self.workdir,
                timeout=self.speak_timeout,
            )

            # Save the new session_id for future --resume
            if result.get("session_id"):
                self._update_worker_session(speaker, result["session_id"])

            reply = result.get("reply", "")

            # Check for API errors (rate limit, authorization failed)
            # Note: we match full error phrases, not bare "429" — a reply
            # mentioning "line 429" or "port 429" should NOT trigger retry.
            reply_lower = reply.lower().strip()
            is_api_error = (
                result.get("error")
                or "api call failed" in reply_lower
                or "rate limit" in reply_lower
                or "rate_limit" in reply_lower
                or "authorization failed" in reply_lower
                or "http 429" in reply_lower
                or "http 503" in reply_lower
            )

            if is_api_error and attempt < max_retries - 1:
                # API error — wait briefly and retry
                wait_sec = 10 * (attempt + 1)  # 10s, 20s, 30s
                logger.warning(
                    "Speaker %s hit API error (attempt %d/%d), "
                    "waiting %ds before retry: %s",
                    speaker, attempt + 1, max_retries, wait_sec,
                    reply[:100],
                )
                import time as _time
                _time.sleep(wait_sec)
                # Clear session on error — fresh start may help
                self._clear_worker_session(speaker)
                continue

            # Success or final attempt exhausted
            # If the speaker returned an error placeholder, keep the session
            # so the next attempt can resume with context.
            return reply

        return reply  # last attempt's result

    def _investigator_speak(
        self, investigator: str, title: str, dispatch_task: str,
    ) -> str:
        """Spawn a worker to investigate a specific question.

        This is different from a normal speaker turn: instead of giving
        an opinion, the worker uses its tools (web_search, read_file,
        terminal, etc.) to gather concrete information and report findings.
        """
        history = self._build_history()
        prompt = (
            f"You are **{investigator}** in an Agora team discussion.\n"
            f"The chair has dispatched you to investigate a specific question.\n"
            f"Use your tools (web_search, read_file, terminal, skill_manage, etc.) "
            f"to gather concrete information.\n\n"
            f"## Topic\n{title}\n\n"
            f"## Investigation Task\n{dispatch_task}\n\n"
            f"## Discussion Context\n{history[:8000]}\n\n"
            f"## Instructions\n"
            f"1. Use your tools to investigate the task thoroughly.\n"
            f"2. Report your findings clearly: what you found, with evidence.\n"
            f"3. If you found relevant code, data, or test results, include specifics.\n"
            f"4. Conclude with how your findings affect the discussion.\n\n"
            f"After your investigation, output your report on a new line starting with:\n"
            f"DISCUSSION_REPLY: <your findings>"
        )

        session_id = self._get_worker_session(investigator)

        result = spawn_agent_speak(
            profile_name=investigator,
            prompt=prompt,
            session_id=session_id,
            workdir=self.workdir,
            # Investigations may take longer (web search, running tests)
            timeout=self.speak_timeout + 240,
        )

        if result.get("session_id"):
            self._update_worker_session(investigator, result["session_id"])

        return result.get("reply", "")

    def _spawn_with_retry(
        self, profile: str, prompt: str,
    ) -> dict:
        """Spawn an agent with 429 retry protection. Used for voting."""
        max_retries = 10
        result = {}
        for attempt in range(max_retries):
            session_id = self._get_worker_session(profile)
            result = spawn_agent_speak(
                profile_name=profile,
                prompt=prompt,
                session_id=session_id,
                workdir=self.workdir,
                timeout=self.speak_timeout,
            )
            if result.get("session_id"):
                self._update_worker_session(profile, result["session_id"])

            reply = result.get("reply", "")
            reply_lower = reply.lower().strip()
            is_api_error = (
                result.get("error")
                or "api call failed" in reply_lower
                or "rate limit" in reply_lower
                or "rate_limit" in reply_lower
                or "authorization failed" in reply_lower
                or "http 429" in reply_lower
                or "http 503" in reply_lower
            )
            if is_api_error and attempt < max_retries - 1:
                import time as _time
                _time.sleep(10 * (attempt + 1))
                self._clear_worker_session(profile)
                continue
            return result
        return result

    # ------------------------------------------------------------------ #
    #  Voting                                                            #
    # ------------------------------------------------------------------ #

    def _run_voting(self, title: str) -> list[dict]:
        """Run a formal vote. Each participant votes, then chair decides."""
        db.update_motion_state(self.motion_id, "voting")

        # Chair announces the vote
        history = self._build_history()
        vote_call = CHAIR_VOTE_CALL_PROMPT.format(
            title=_escape_format(title),
            discussion_history=history[:3000],
        )
        call_result = spawn_chair_speak(
            self.chair_profile, vote_call,
            workdir=self.workdir,
            timeout=self.chair_timeout,
        )
        if call_result.get("reply"):
            db.add_message(
                motion_id=self.motion_id,
                role=self.chair_profile,
                round_num=0,
                stance="neutral",
                content=call_result["reply"],
                step_type="vote_call",
                is_chair=True,
            )

        # Each participant votes (serial)
        votes = []
        for participant in self.participants:
            vote_prompt = build_vote_prompt(participant, title, history)

            # Spawn with 429 retry protection
            result = self._spawn_with_retry(participant, vote_prompt)

            vote_data = parse_json_response(result.get("reply", ""))
            if vote_data is None:
                vote_data = {"vote": "abstain", "reason": "No clear vote"}

            vote = vote_data.get("vote", "abstain")
            reason = vote_data.get("reason", "")

            db.add_vote(
                motion_id=self.motion_id,
                role=participant,
                vote=vote,
                reason=reason,
            )
            votes.append({"role": participant, "vote": vote, "reason": reason})

            db.add_message(
                motion_id=self.motion_id,
                role=participant,
                round_num=0,
                stance=vote,
                content=f"Vote: {vote} — {reason}",
                step_type="vote",
            )

        logger.info("Voting complete: %s", votes)
        return votes

    def _run_forced_vote(self, title: str) -> list[dict]:
        """Force a vote when max_steps is reached without chair closing.

        Unlike _run_voting (where chair voluntarily calls vote and announces
        what's being voted on), here the chair is forced to:
        1. Read the full discussion history
        2. Summarize the key points of agreement/disagreement
        3. Formulate a concrete proposal
        4. Ask participants to vote adopt/reject on that proposal

        This ensures the vote has clear content even when the discussion
        was cut short.
        """
        db.update_motion_state(self.motion_id, "voting")
        history = self._build_history()

        # Chair: summarize discussion + formulate a concrete proposal
        forced_prompt = (
            f"You are chairing an Agora discussion that has reached the step limit.\n"
            f"The discussion must end now with a vote.\n\n"
            f"## Topic\n{title}\n\n"
            f"## Full Discussion\n{history[:4000]}\n\n"
            f"Your job:\n"
            f"1. Summarize the key points of agreement and disagreement (2-3 sentences)\n"
            f"2. Formulate ONE concrete proposal that captures the best path forward\n"
            f"3. Ask participants to vote adopt or reject on this proposal\n\n"
            f"Be specific. The proposal must be actionable, not vague.\n"
            f"Output your summary and proposal in 3-5 sentences.\n"
        )

        call_result = spawn_chair_speak(
            self.chair_profile, forced_prompt,
            workdir=self.workdir,
            timeout=self.chair_timeout,
        )
        if call_result.get("reply"):
            db.add_message(
                motion_id=self.motion_id,
                role=self.chair_profile,
                round_num=0,
                stance="neutral",
                content=call_result["reply"],
                step_type="vote_call",
                is_chair=True,
            )

        # Each participant votes on the chair's proposal
        chair_proposal = call_result.get("reply", "")
        votes = []
        for participant in self.participants:
            vote_prompt = (
                f"You are **{participant}** in an Agora discussion. The chair has "
                f"proposed the following. Please vote.\n\n"
                f"## Topic\n{title}\n\n"
                f"## Chair's Proposal\n{chair_proposal}\n\n"
                f"## Discussion Context\n{history[:8000]}\n\n"
                f"Cast your vote. Respond with JSON ONLY:\n"
                f'{{"vote": "adopt" | "reject" | "abstain", "reason": "<1-2 sentences>"}}\n'
            )
            result = self._spawn_with_retry(participant, vote_prompt)

            vote_data = parse_json_response(result.get("reply", ""))
            if vote_data is None:
                vote_data = {"vote": "abstain", "reason": "No clear vote"}

            vote = vote_data.get("vote", "abstain")
            reason = vote_data.get("reason", "")

            db.add_vote(
                motion_id=self.motion_id,
                role=participant,
                vote=vote,
                reason=reason,
            )
            votes.append({"role": participant, "vote": vote, "reason": reason})

            db.add_message(
                motion_id=self.motion_id,
                role=participant,
                round_num=0,
                stance=vote,
                content=f"Vote: {vote} — {reason}",
                step_type="vote",
            )

        logger.info("Forced voting complete: %s", votes)
        return votes

    # ------------------------------------------------------------------ #
    #  Finalize                                                          #
    # ------------------------------------------------------------------ #

    def _finalize(self, title: str, motion: dict) -> DiscussionResult:
        """Generate summary, create tasks, close motion."""
        db.update_motion_state(self.motion_id, "summarizing")

        history = self._build_history()
        votes = db.get_votes(self.motion_id)
        vote_summary = ""
        if votes:
            vote_lines = [f"  {v['role']}: {v['vote']} — {v.get('reason', '')}" for v in votes]
            vote_summary = "## Votes\n" + "\n".join(vote_lines)

        prompt = CHAIR_SUMMARY_PROMPT.format(
            title=_escape_format(title),
            discussion_history=history[:6000],
            vote_summary=vote_summary,
            participants=", ".join(self.participants),
        )

        result = spawn_chair_speak(
            self.chair_profile, prompt,
            workdir=self.workdir,
            timeout=self.chair_timeout,
        )

        summary_data: dict[str, Any] = {}
        if result.get("reply"):
            summary_data = parse_json_response(result["reply"]) or {}

        if not summary_data:
            summary_data = {
                "summary": f"Discussion completed after {motion.get('step_count', 0)} steps.",
                "action_items": [],
                "confidence": 0.5,
                "decision": "no_consensus",
            }

        decision = summary_data.get("decision", "no_consensus")
        action_items = summary_data.get("action_items", [])
        action_item_strings = [
            ai.get("item", str(ai)) if isinstance(ai, dict) else str(ai)
            for ai in action_items
        ]

        # Close the motion
        db.update_motion_status(
            self.motion_id,
            status="closed",
            decision=decision,
            rationale=summary_data.get("summary", ""),
            action_items=action_item_strings,
        )
        db.update_motion_state(self.motion_id, "closed")
        db.save_discussion_state(self.motion_id, current_state="closed")

        # Create kanban tasks from action items
        created_tasks: list[str] = []
        if action_items:
            created_tasks = self._create_kanban_tasks(
                motion_id=self.motion_id,
                title=title,
                action_items=action_items,
                source_task_id=motion.get("source_task_id"),
            )

        logger.info(
            "Discussion finalized: motion=%s decision=%s tasks=%d",
            self.motion_id, decision, len(created_tasks),
        )

        return DiscussionResult(
            motion_id=self.motion_id,
            decision=decision,
            summary=summary_data.get("summary", ""),
            action_items=action_items,
            confidence=summary_data.get("confidence", 0.0),
            steps_completed=motion.get("step_count", 0),
            votes=votes,
            created_tasks=created_tasks,
        )

    # ------------------------------------------------------------------ #
    #  Helpers                                                           #
    # ------------------------------------------------------------------ #

    def _build_history(self) -> str:
        """Build a text summary of all messages so far."""
        messages = db.get_messages(self.motion_id)
        if not messages:
            return "(no messages yet)"
        lines = []
        for msg in messages:
            speaker = msg.get("role", "?")
            chair_tag = " [Chair]" if msg.get("is_chair") else ""
            step_type = msg.get("step_type", "speak")
            content = msg.get("content", "")[:1000]
            lines.append(f"[{speaker}{chair_tag} ({step_type})]: {content}")
        return "\n\n".join(lines)

    def _infer_stance(self, text: str) -> str:
        """Simple heuristic to infer stance from response text.

        Uses word-boundary regex to avoid false positives (e.g. ``"disagree"``
        contains the substring ``"agree"`` but should count as opposition, not
        support).
        """
        import re
        lower = text.lower()
        support_words = ["agree", "support", "recommend", "endorse", "approve"]
        oppose_words = ["disagree", "oppose", "reject", "concern", "risk"]
        # Use negative lookbehind to avoid matching "agree" inside "disagree"
        support = sum(
            1 for w in support_words
            if re.search(r'(?<!dis)' + re.escape(w) + r'\b', lower)
        )
        oppose = sum(1 for w in oppose_words if re.search(r'\b' + re.escape(w) + r'\b', lower))
        if support > oppose + 1:
            return "support"
        elif oppose > support + 1:
            return "oppose"
        return "neutral"

    def _fetch_task_context(self, source_task_id: str | None) -> str:
        """Fetch the source kanban task body for context."""
        if not source_task_id:
            return ""
        try:
            from agora.kanban_compat import kanban_db
            conn = kanban_db.connect()
            try:
                task = kanban_db.get_task(conn, source_task_id)
                if task and task.body:
                    return f"Source task: {task.title}\n{task.body[:8000]}"
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("Failed to fetch task context: %s", exc)
        return ""

    def _get_worker_session(self, worker_name: str) -> str | None:
        """Get a worker's per-project session_id from the registry.

        Uses the project_name to isolate sessions across projects.
        Falls back to the legacy global session_id for backward compat.
        """
        try:
            from agora.worker_manager import get_worker_session
            session_id = get_worker_session(worker_name, self.project_name or None)

            # Check session size — rotate if too large
            if session_id:
                try:
                    from agora.session_manager import check_session_size, rotate_session
                    size_info = check_session_size(worker_name, session_id)
                    if size_info.get("needs_rotation"):
                        logger.info(
                            "Rotating session for %s/%s (messages=%d, size=%.1fKB)",
                            worker_name, self.project_name,
                            size_info.get("message_count", 0),
                            size_info.get("size_kb", 0),
                        )
                        rotate_session(worker_name, worker_name)
                        return None  # force new session on next spawn
                except Exception as exc:
                    logger.debug("Session size check failed for %s: %s", worker_name, exc)

            return session_id
        except Exception:
            return None

    def _update_worker_session(self, worker_name: str, session_id: str) -> None:
        """Update a worker's per-project session_id in the registry."""
        try:
            from agora.worker_manager import update_worker_session
            update_worker_session(worker_name, session_id, self.project_name or None)
        except Exception as exc:
            logger.debug("Failed to update session for %s: %s", worker_name, exc)

    def _clear_worker_session(self, worker_name: str) -> None:
        """Clear a worker's session_id so the next spawn creates a fresh one."""
        try:
            from agora.worker_manager import update_worker_session
            update_worker_session(worker_name, None, self.project_name or None)
            logger.info("Cleared session for %s (will create fresh on next spawn)", worker_name)
        except Exception as exc:
            logger.debug("Failed to clear session for %s: %s", worker_name, exc)

    def _consume_human_inputs(self) -> list[dict]:
        """Check for human-injected messages since last step."""
        # Human messages are added via the API with step_type="human_input"
        # They're already in the DB, so _build_history will include them.
        # This is a hook for future expansion (e.g. notifications).
        messages = db.get_messages(self.motion_id)
        return [m for m in messages if m.get("step_type") == "human_input"]

    def _create_kanban_tasks(
        self, motion_id: str, title: str,
        action_items: list, source_task_id: str | None,
    ) -> list[str]:
        """Create kanban tasks from discussion action items."""
        try:
            from agora.kanban_compat import kanban_db
        except ImportError:
            logger.warning("kanban_db not available — skipping task creation")
            return []

        # Determine the board/tenant for this project.
        # Uses the project's board name (e.g. "agora-myproject") for isolation.
        # Falls back to the raw project name for backward compatibility.
        tenant = self.project_name if self.project_name else None
        if self.project_name:
            try:
                from project_planner import get_project
                proj = get_project(self.project_name)
                if proj and proj.get("board"):
                    tenant = proj["board"]
            except Exception:
                pass  # fall back to raw project name

        created: dict[int, str] = {}
        conn = kanban_db.connect()
        try:
            for idx, ai in enumerate(action_items):
                if isinstance(ai, dict):
                    item_title = ai.get("item", str(ai))
                    owner = ai.get("owner", "")
                    depends_on = ai.get("depends_on", [])
                else:
                    item_title = str(ai)
                    owner = ""
                    depends_on = []

                # Map owner to team member
                assignee = owner if owner else None
                if owner and self.project_name:
                    try:
                        from agora.team_manager import get_team_for_project, get_team, get_assignee_for_role
                        from project_planner import get_project
                        # Try direct team_for_project match first
                        team = get_team_for_project(self.project_name)
                        # If not found, try via project registry
                        if not team:
                            proj = get_project(self.project_name)
                            if proj and proj.get("team"):
                                team = get_team(proj["team"])
                        if team:
                            picked = get_assignee_for_role(team["name"], owner)
                            if picked:
                                assignee = picked
                    except Exception:
                        pass

                parent_ids: list[str] = []
                for dep in depends_on:
                    dep_idx = dep - 1 if isinstance(dep, int) else None
                    if dep_idx is not None and dep_idx in created:
                        parent_ids.append(created[dep_idx])

                if not parent_ids and source_task_id:
                    parent_ids = [source_task_id]

                task_id = kanban_db.create_task(
                    conn,
                    title=item_title[:200],
                    body=(
                        f"From Agora discussion: {title}\n"
                        f"Motion: {motion_id}\n"
                        f"Action item {idx + 1}/{len(action_items)}: {item_title}"
                    ),
                    assignee=assignee,
                    workspace_kind="scratch",
                    parents=parent_ids,
                    tenant=tenant,
                )
                created[idx] = task_id
                logger.info("Created kanban task %s: %s", task_id, item_title[:80])
        except Exception as exc:
            logger.error("Failed to create kanban tasks: %s", exc)
        finally:
            conn.close()

        return list(created.values())

    def _abort(self, reason: str) -> DiscussionResult:
        """Abort the discussion with an error."""
        db.update_motion_status(self.motion_id, status="closed", decision="error")
        db.update_motion_state(self.motion_id, "closed")
        db.save_discussion_state(self.motion_id, current_state="closed")
        logger.error("Discussion aborted: %s", reason)
        return DiscussionResult(motion_id=self.motion_id, decision="error")
