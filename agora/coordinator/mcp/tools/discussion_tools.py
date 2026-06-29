"""Discussion MCP tools: create_motion, get_motion_messages, vote, close_motion, create_task.

These tools let any agent participate in structured discussions (motions),
and let the coordinator/moderator agent orchestrate the deliberation flow.

Core flow:
  1. create_motion — start a topic for discussion
  2. send_message — agents discuss (multiple rounds, via comm_tools.py)
  3. vote — agents vote on the motion
  4. close_motion — moderator closes with a final decision
  5. create_task — moderator dispatches work based on decision
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from ..deps import get_storage
from ..server import mcp_server

logger = logging.getLogger(__name__)


@mcp_server.tool()
async def create_motion(
    title: str,
    description: str = "",
    context: str = "",
    rounds: int = 3,
    voting_method: str = "simple_majority",
) -> dict:
    """Create a new motion (topic for discussion).

    Any agent can create a motion to raise a topic for team discussion.
    The motion starts in 'discussing' status so agents can immediately
    send messages via send_message.

    Args:
        title: Short title for the motion (e.g. "Use PostgreSQL for storage")
        description: Detailed description of what's being discussed
        context: Background information, constraints, links to relevant files
        rounds: Number of discussion rounds (default 3)
        voting_method: How to decide — simple_majority | supermajority | unanimous

    Returns:
        Motion ID and initial status
    """
    storage = get_storage()
    agent_id = _get_current_agent_id()

    motion = await storage.create_motion(
        title=title,
        description=description,
        rounds=rounds,
        voting_method=voting_method,
        context=context,
    )
    motion_id = motion["id"]

    # Immediately transition to 'discussing' so agents can send messages
    await storage.update_motion_status(motion_id, "discussing")

    logger.info(
        "Motion %s created by agent %s: %s",
        motion_id, agent_id, title,
    )

    # Notify other agents via event bus
    _notify_motion_event(motion_id, agent_id, "MOTION_CREATED", {"title": title})

    return {
        "motion_id": motion_id,
        "title": title,
        "status": "discussing",
        "rounds": rounds,
        "created_by": agent_id,
    }


@mcp_server.tool()
async def get_motion_messages(
    motion_id: str,
    round_num: int | None = None,
    limit: int = 50,
) -> dict:
    """Get discussion messages for a motion.

    Args:
        motion_id: The motion ID
        round_num: If specified, only get messages from this round
        limit: Maximum messages to return

    Returns:
        List of messages with sender, stance, content, and round number
    """
    storage = get_storage()

    motion = await storage.get_motion(motion_id)
    if motion is None:
        return {"error": "Motion not found", "code": 404}

    messages = await storage.get_messages(motion_id)
    if round_num is not None:
        messages = [m for m in messages if m.get("round_num") == round_num]

    return {
        "motion_id": motion_id,
        "title": motion.get("title", ""),
        "status": motion.get("status", ""),
        "current_round": motion.get("current_round", 0),
        "rounds": motion.get("rounds", 3),
        "decision": motion.get("decision"),
        "rationale": motion.get("rationale"),
        "messages": [
            {
                "message_id": str(m.get("id", "")),
                "sender_id": m.get("agent_id", ""),
                "round": m.get("round_num", 1),
                "stance": m.get("stance", "neutral"),
                "content": m.get("content", ""),
                "timestamp": m.get("timestamp", ""),
            }
            for m in messages[:limit]
        ],
        "total": len(messages),
    }


@mcp_server.tool()
async def vote(
    motion_id: str,
    vote_choice: str,
    reason: str = "",
    confidence: float = 0.8,
) -> dict:
    """Cast a vote on a motion.

    Args:
        motion_id: The motion to vote on
        vote_choice: yes | no | abstain
        reason: Explanation for the vote
        confidence: Confidence level 0.0 to 1.0

    Returns:
        Confirmation of the vote
    """
    storage = get_storage()
    agent_id = _get_current_agent_id()

    valid_choices = {"yes", "no", "abstain"}
    if vote_choice not in valid_choices:
        return {
            "error": f"Invalid vote '{vote_choice}'. Must be one of {valid_choices}",
        }

    motion = await storage.get_motion(motion_id)
    if motion is None:
        return {"error": "Motion not found", "code": 404}

    if motion.get("status") not in ("discussing", "voting"):
        return {
            "error": f"Cannot vote on motion in status '{motion.get('status')}'",
            "code": 409,
        }

    # Check if already voted
    has_voted = await storage.has_voted(motion_id, agent_id)
    if has_voted:
        return {"error": "Already voted on this motion", "code": 409}

    vote_id = await storage.add_vote(
        motion_id=motion_id,
        agent_id=agent_id,
        vote=vote_choice,
        confidence=confidence,
        reason=reason,
    )

    logger.info(
        "Vote on motion %s by agent %s: %s",
        motion_id, agent_id, vote_choice,
    )

    return {
        "vote_id": str(vote_id),
        "motion_id": motion_id,
        "vote": vote_choice,
        "reason": reason,
    }


@mcp_server.tool()
async def close_motion(
    motion_id: str,
    decision: str,
    rationale: str = "",
    action_items: list[str] | None = None,
) -> dict:
    """Close a motion with a final decision (moderator only).

    The moderator can close a motion at any time, with or without a vote.
    The decision is recorded and all participants are notified.

    Args:
        motion_id: The motion to close
        decision: adopted | rejected | deferred
        rationale: Explanation for the decision
        action_items: List of action items resulting from this decision

    Returns:
        Confirmation with vote summary if votes were cast
    """
    storage = get_storage()
    agent_id = _get_current_agent_id()

    motion = await storage.get_motion(motion_id)
    if motion is None:
        return {"error": "Motion not found", "code": 404}

    if motion.get("status") in ("completed", "closed"):
        return {"error": "Motion already closed", "code": 409}

    # Get vote summary if any votes were cast
    vote_summary = {}
    try:
        votes = await storage.get_votes(motion_id)
        if votes:
            summary = {"yes": 0, "no": 0, "abstain": 0, "total": len(votes)}
            for v in votes:
                choice = v.get("vote", "abstain")
                summary[choice] = summary.get(choice, 0) + 1
            vote_summary = summary
    except Exception:
        pass

    # Update motion status to closed with decision
    await storage.update_motion_status(
        motion_id, "closed",
        decision=decision,
        rationale=rationale,
        action_items=action_items or [],
    )

    logger.info(
        "Motion %s closed by agent %s: decision=%s votes=%s",
        motion_id, agent_id, decision, vote_summary,
    )

    # Notify participants
    _notify_motion_event(motion_id, agent_id, "MOTION_CLOSED", {"decision": decision})

    return {
        "motion_id": motion_id,
        "decision": decision,
        "rationale": rationale,
        "action_items": action_items or [],
        "vote_summary": vote_summary,
        "closed_by": agent_id,
    }


@mcp_server.tool()
async def create_task(
    title: str,
    description: str = "",
    assigned_to: str = "",
    priority: str = "normal",
    depends_on: list[str] | None = None,
    motion_id: str = "",
) -> dict:
    """Create a new task and optionally assign it to an agent.

    Typically used by the moderator to dispatch work based on
    discussion outcomes.

    Args:
        title: Short task title
        description: Detailed task description
        assigned_to: Agent ID to assign to (empty = unassigned/pending)
        priority: low | normal | high | critical
        depends_on: List of task IDs this task depends on
        motion_id: Link to the motion that led to this task

    Returns:
        Created task details
    """
    storage = get_storage()
    agent_id = _get_current_agent_id()

    # Import TaskNode
    from ...task_models import TaskNode, TaskStatus

    task_id = f"task-{uuid.uuid4().hex[:12]}"
    graph_id = f"graph-{uuid.uuid4().hex[:12]}"

    # Create a task graph for this task
    await storage.create_task_graph(
        graph_id=graph_id,
        motion_id=motion_id or None,
    )

    status = "assigned" if assigned_to else "pending"
    task = TaskNode(
        id=task_id,
        graph_id=graph_id,
        motion_id=motion_id or None,
        title=title,
        description=description,
        status=TaskStatus(status),
        assigned_to=assigned_to or None,
        required_capabilities=[],
        depends_on=depends_on or [],
    )
    result = await storage.create_task(task)

    logger.info(
        "Task %s created by agent %s: %s (assigned_to=%s)",
        task_id, agent_id, title, assigned_to or "unassigned",
    )

    return {
        "task_id": task_id,
        "title": title,
        "status": status,
        "assigned_to": assigned_to or None,
        "created_by": agent_id,
    }


@mcp_server.tool()
async def list_motions(
    status_filter: str = "active",
    limit: int = 20,
) -> dict:
    """List motions (discussions) the agent can see.

    Args:
        status_filter: active | closed | all
        limit: Maximum motions to return

    Returns:
        List of motions with title, status, and round info
    """
    storage = get_storage()

    status_map = {
        "active": None,  # all non-closed
        "closed": "closed",
        "all": None,
    }

    motions = await storage.list_motions(limit=limit)

    if status_filter == "active":
        motions = [m for m in motions if m.get("status") not in ("closed", "completed")]
    elif status_filter == "closed":
        motions = [m for m in motions if m.get("status") in ("closed", "completed")]

    return {
        "motions": [
            {
                "motion_id": m.get("id", ""),
                "title": m.get("title", ""),
                "status": m.get("status", ""),
                "current_round": m.get("current_round", 0),
                "rounds": m.get("rounds", 3),
                "decision": m.get("decision"),
                "created_at": m.get("created_at", ""),
            }
            for m in motions[:limit]
        ],
        "total": len(motions),
    }


# --- Helpers ---

def _get_current_agent_id() -> str:
    """Extract agent_id from MCP context."""
    try:
        ctx = mcp_server.get_context()
        request = ctx.request_context.request
        aid = getattr(request.state, "mcp_agent_id", None)
        if aid:
            return aid
        # Fallback: session_map lookup
        mcp_sid = request.headers.get("mcp-session-id")
        if mcp_sid:
            try:
                from ..deps import get_session_map
                sm = get_session_map()
                looked_up = sm.get_agent_id(mcp_sid)
                if looked_up:
                    return looked_up
            except RuntimeError:
                pass
        return "unknown"
    except Exception:
        return "unknown"


def _notify_motion_event(motion_id: str, agent_id: str, event_type: str, payload: dict):
    """Broadcast motion event via event bus."""
    try:
        from ...event_bus import publish
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(publish(event_type, {
                "motion_id": motion_id,
                "agent_id": agent_id,
                **payload,
            }, channel="discussions"))
    except Exception as exc:
        logger.debug("Failed to notify motion event: %s", exc)
