"""Event-driven discussion driver for Agora v2.0.

Replaces the old round-robin ctx.llm.complete approach with:
  - Real agent subprocess spawns (hermes -p <profile> chat -q)
  - Leader as chair: opens, evaluates, redirects, calls votes, summarizes
  - Event-driven flow: Leader picks next speaker dynamically
  --resume preserves conversation context across kanban tasks and discussions
  - Memory persistence: results written to each participant's MEMORY.md

Flow:
  1. Chair (Leader) opens → names first speaker + guidance
  2. Speaker speaks (spawn agent with --resume) → message stored
  3. Chair evaluates → continue? vote? close?
  4. Repeat 2-3 until close or max_steps
  5. (Optional) Vote: each participant votes → chair decides
  6. Summary: chair generates action items + writes memory
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..storage import motions as db
from ..utils import get_global_root, parse_json_response
from .agent_spawn import spawn_agent_speak, spawn_chair_speak
from .chair import (
    CHAIR_EVALUATE_PROMPT,
    CHAIR_OPENING_PROMPT,
    CHAIR_SUMMARY_PROMPT,
    CHAIR_VOTE_CALL_PROMPT,
    build_speaker_prompt,
    build_vote_prompt,
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
        speak_timeout: int = 300,
        chair_timeout: int = 120,
    ) -> None:
        self.motion_id = motion_id
        self.chair_profile = chair_profile
        self.participants = participants
        self.workdir = workdir or None
        self.project_name = project_name
        self.max_steps = max_steps
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
            action = self._chair_evaluate(title)
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
                logger.info("Chair called close at step %d", step)
                break
            elif next_action == "vote":
                logger.info("Chair called vote at step %d", step)
                self._run_voting(title)
                break
            else:  # continue
                db.save_discussion_state(
                    self.motion_id, "discussing",
                    next_speaker=action.get("next_speaker"),
                    last_guidance=action.get("guidance"),
                    last_action="continue",
                )

        # --- Finalize: summary + memory ---
        return self._finalize(title, motion)

    # ------------------------------------------------------------------ #
    #  Chair calls                                                       #
    # ------------------------------------------------------------------ #

    def _chair_open(
        self, title: str, description: str, task_context: str,
    ) -> dict | None:
        """Chair opens the discussion."""
        prompt = CHAIR_OPENING_PROMPT.format(
            title=title,
            description=description,
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
            logger.error("Chair open returned non-JSON: %s", result["reply"][:200])
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

    def _chair_evaluate(self, title: str) -> dict | None:
        """Chair evaluates the discussion after each speaker."""
        history = self._build_history()
        prompt = CHAIR_EVALUATE_PROMPT.format(
            title=title,
            participants=", ".join(self.participants),
            discussion_history=history,
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
            logger.warning("Chair evaluate returned non-JSON, defaulting to close")
            return {"action": "close", "reason": "Chair returned non-JSON, forcing close"}
        return data

    # ------------------------------------------------------------------ #
    #  Speaker calls                                                     #
    # ------------------------------------------------------------------ #

    def _speaker_speak(
        self, speaker: str, title: str, description: str,
        guidance: str, task_context: str,
    ) -> str:
        """Spawn a worker agent to speak in the discussion."""
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

        return result.get("reply", "")

    # ------------------------------------------------------------------ #
    #  Voting                                                            #
    # ------------------------------------------------------------------ #

    def _run_voting(self, title: str) -> list[dict]:
        """Run a formal vote. Each participant votes, then chair decides."""
        db.update_motion_state(self.motion_id, "voting")

        # Chair announces the vote
        history = self._build_history()
        vote_call = CHAIR_VOTE_CALL_PROMPT.format(
            title=title,
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
            session_id = self._get_worker_session(participant)

            result = spawn_agent_speak(
                profile_name=participant,
                prompt=vote_prompt,
                session_id=session_id,
                workdir=self.workdir,
                timeout=min(self.speak_timeout, 120),
            )

            if result.get("session_id"):
                self._update_worker_session(participant, result["session_id"])

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

    # ------------------------------------------------------------------ #
    #  Finalize                                                          #
    # ------------------------------------------------------------------ #

    def _finalize(self, title: str, motion: dict) -> DiscussionResult:
        """Generate summary, create tasks, write memory, close motion."""
        db.update_motion_state(self.motion_id, "summarizing")

        history = self._build_history()
        votes = db.get_votes(self.motion_id)
        vote_summary = ""
        if votes:
            vote_lines = [f"  {v['role']}: {v['vote']} — {v.get('reason', '')}" for v in votes]
            vote_summary = "## Votes\n" + "\n".join(vote_lines)

        prompt = CHAIR_SUMMARY_PROMPT.format(
            title=title,
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

        # Create kanban tasks from action items
        created_tasks: list[str] = []
        if action_items:
            created_tasks = self._create_kanban_tasks(
                motion_id=self.motion_id,
                title=title,
                action_items=action_items,
                source_task_id=motion.get("source_task_id"),
            )

        # Write memory to each participant
        self._write_participant_memories(title, summary_data, votes)

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
            content = msg.get("content", "")[:500]
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
        oppose = sum(1 for w in oppose_words if w in lower)
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
            from hermes_cli import kanban_db
            conn = kanban_db.connect()
            try:
                task = kanban_db.get_task(conn, source_task_id)
                if task and task.body:
                    return f"Source task: {task.title}\n{task.body[:2000]}"
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("Failed to fetch task context: %s", exc)
        return ""

    def _get_worker_session(self, worker_name: str) -> str | None:
        """Get a worker's session_id from the registry.

        Before returning the session_id, checks whether the session has
        grown too large (> 200 messages or > 500 KB).  If so, rotates it
        — writes a memory summary and clears the stored session_id —
        then returns ``None`` so the next spawn creates a fresh session.
        """
        try:
            from ..worker_manager import get_worker_session
            session_id = get_worker_session(worker_name)

            # Check session size — rotate if too large
            if session_id:
                try:
                    from ..session_manager import check_session_size, rotate_session
                    size_info = check_session_size(worker_name, session_id)
                    if size_info.get("needs_rotation"):
                        logger.info(
                            "Rotating session for %s (messages=%d, size=%.1fKB)",
                            worker_name,
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
        """Update a worker's session_id in the registry."""
        try:
            from ..worker_manager import update_worker_session
            update_worker_session(worker_name, session_id)
        except Exception as exc:
            logger.debug("Failed to update session for %s: %s", worker_name, exc)

    def _consume_human_inputs(self) -> list[dict]:
        """Check for human-injected messages since last step."""
        # Human messages are added via the API with step_type="human_input"
        # They're already in the DB, so _build_history will include them.
        # This is a hook for future expansion (e.g. notifications).
        messages = db.get_messages(self.motion_id)
        return [m for m in messages if m.get("step_type") == "human_input"]

    def _write_participant_memories(
        self, title: str, summary_data: dict, votes: list[dict],
    ) -> None:
        """Write discussion results to each participant's MEMORY.md."""
        global_root = get_global_root()

        for participant in self.participants:
            try:
                # Find the participant's profile directory
                profile_dir = global_root / "profiles" / participant
                if not profile_dir.exists():
                    continue

                memory_path = profile_dir / "MEMORY.md"
                # Find this participant's stance
                their_vote = next(
                    (v for v in votes if v["role"] == participant), None
                )
                stance_desc = ""
                if their_vote:
                    stance_desc = f"My vote: {their_vote['vote']} — {their_vote.get('reason', '')}"

                decision = summary_data.get("decision", "unknown")
                summary_text = summary_data.get("summary", "")

                entry = (
                    f"\nAgora discussion ({self.motion_id}): \"{title}\"\n"
                    f"  {stance_desc}\n"
                    f"  Decision: {decision} — {summary_text[:150]}\n"
                )
                if len(entry) > 300:
                    entry = entry[:297] + "...\n"

                # Append to MEMORY.md
                if memory_path.exists():
                    current = memory_path.read_text()
                    memory_path.write_text(current + entry)
                else:
                    memory_path.write_text(f"# {participant} Memory\n{entry}")

                logger.info("Wrote memory for %s", participant)
            except Exception as exc:
                logger.warning("Failed to write memory for %s: %s", participant, exc)

        # Write to chair's memory too
        try:
            profile_dir = global_root / "profiles" / self.chair_profile
            if profile_dir.exists():
                memory_path = profile_dir / "MEMORY.md"
                vote_summary = ", ".join(
                    f"{v['role']}={v['vote']}" for v in votes
                ) if votes else "no vote"
                entry = (
                    f"\nAgora motion {self.motion_id} resolved: \"{title}\" → "
                    f"{summary_data.get('decision', 'unknown')}\n"
                    f"  Votes: {vote_summary}\n"
                    f"  {len(summary_data.get('action_items', []))} action items created.\n"
                )
                if memory_path.exists():
                    current = memory_path.read_text()
                    memory_path.write_text(current + entry)
                else:
                    memory_path.write_text(f"# {self.chair_profile} Memory\n{entry}")
        except Exception as exc:
            logger.warning("Failed to write chair memory: %s", exc)

    def _create_kanban_tasks(
        self, motion_id: str, title: str,
        action_items: list, source_task_id: str | None,
    ) -> list[str]:
        """Create kanban tasks from discussion action items."""
        try:
            from hermes_cli import kanban_db
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
                        from ..team_manager import get_team_for_project, get_assignee_for_role
                        team = get_team_for_project(self.project_name)
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
        logger.error("Discussion aborted: %s", reason)
        return DiscussionResult(motion_id=self.motion_id, decision="error")
