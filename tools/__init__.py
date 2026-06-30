"""Agora tools — registered with Hermes plugin system.

Tools:
  - agora_raise_motion    — agent/user initiates a discussion
  - agora_get_messages    — read discussion messages
  - agora_get_result      — read closed discussion result
  - agora_list_motions    — list active/closed discussions
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Schema definitions for each tool — Hermes uses these to generate
# the tool descriptions visible to the LLM.

_RAISE_MOTION_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "Short title for the discussion topic",
        },
        "description": {
            "type": "string",
            "description": "Detailed description of what's being discussed",
        },
        "context": {
            "type": "string",
            "description": "Where this motion originated (e.g. task ID + what triggered it)",
        },
        "priority": {
            "type": "string",
            "enum": ["low", "normal", "high"],
            "default": "normal",
        },
        "blocking": {
            "type": "boolean",
            "default": False,
            "description": "If true, block the current kanban task until discussion completes",
        },
        "participants": {
            "type": "array",
            "items": {"type": "string", "enum": ["architect", "developer", "reviewer"]},
            "description": "Which roles participate (default: all three)",
        },
        "rounds": {
            "type": "integer",
            "default": 3,
            "description": "Maximum discussion rounds",
        },
        "template": {
            "type": "string",
            "enum": ["tech_choice", "bug_analysis", "architecture_review", "security_audit"],
            "description": "Use a discussion template to pre-configure participants, rounds, and focus areas",
        },
    },
    "required": ["title"],
}

_GET_MESSAGES_SCHEMA = {
    "type": "object",
    "properties": {
        "motion_id": {"type": "string", "description": "The motion ID"},
        "round": {"type": "integer", "description": "Filter to specific round (optional)"},
    },
    "required": ["motion_id"],
}

_GET_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "motion_id": {"type": "string", "description": "The motion ID"},
    },
    "required": ["motion_id"],
}

_LIST_MOTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["active", "closed", "all"],
            "default": "active",
        },
        "limit": {"type": "integer", "default": 20},
    },
}


def register_all_tools(ctx: Any) -> None:
    """Register all Agora tools and the /agora slash command."""
    from ..agora.storage import motions as db
    from ..agora.discussion.driver import DiscussionDriver

    # --- Tool: agora_raise_motion ---
    async def _raise_motion_handler(args: dict, **kwargs) -> dict:
        return await _handle_raise_motion(ctx, args)

    ctx.register_tool(
        name="agora_raise_motion",
        toolset="agora",
        schema=_RAISE_MOTION_SCHEMA,
        handler=_raise_motion_handler,
        is_async=True,
        description="Raise a motion for team discussion. The LLM-driven discussion engine will simulate architect/developer/reviewer debate and produce action items.",
        emoji="🏛️",
    )

    # --- Tool: agora_get_messages ---
    def _get_messages_handler(args: dict, **kwargs) -> dict:
        motion_id = args.get("motion_id", "")
        round_num = args.get("round")

        motion = db.get_motion(motion_id)
        if motion is None:
            return {"error": "Motion not found", "code": 404}

        messages = db.get_messages(motion_id, round_num=round_num)
        return {
            "motion_id": motion_id,
            "title": motion["title"],
            "status": motion["status"],
            "current_round": motion["current_round"],
            "max_rounds": motion["max_rounds"],
            "messages": [
                {
                    "id": m["id"],
                    "role": m["role"],
                    "round": m["round_num"],
                    "stance": m["stance"],
                    "content": m["content"],
                    "timestamp": m["timestamp"],
                }
                for m in messages
            ],
            "total": len(messages),
        }

    ctx.register_tool(
        name="agora_get_messages",
        toolset="agora",
        schema=_GET_MESSAGES_SCHEMA,
        handler=_get_messages_handler,
        description="Read discussion messages for a motion.",
        emoji="💬",
    )

    # --- Tool: agora_get_result ---
    def _get_result_handler(args: dict, **kwargs) -> dict:
        motion_id = args.get("motion_id", "")
        motion = db.get_motion(motion_id)
        if motion is None:
            return {"error": "Motion not found", "code": 404}

        if motion["status"] != "closed":
            return {
                "motion_id": motion_id,
                "status": motion["status"],
                "message": "Discussion is still in progress.",
            }

        return {
            "motion_id": motion_id,
            "title": motion["title"],
            "status": "closed",
            "decision": motion.get("decision"),
            "rationale": motion.get("rationale"),
            "action_items": motion.get("action_items", []),
            "source": motion.get("source"),
            "source_task_id": motion.get("source_task_id"),
            "closed_at": motion.get("closed_at"),
        }

    ctx.register_tool(
        name="agora_get_result",
        toolset="agora",
        schema=_GET_RESULT_SCHEMA,
        handler=_get_result_handler,
        description="Get the result of a closed discussion (decision, action items).",
        emoji="✅",
    )

    # --- Tool: agora_list_motions ---
    def _list_motions_handler(args: dict, **kwargs) -> dict:
        status_filter = args.get("status", "active")
        limit = args.get("limit", 20)
        motions = db.list_motions(status_filter=status_filter, limit=limit)
        return {
            "motions": [
                {
                    "motion_id": m["id"],
                    "title": m["title"],
                    "status": m["status"],
                    "current_round": m["current_round"],
                    "max_rounds": m["max_rounds"],
                    "decision": m.get("decision"),
                    "source": m.get("source"),
                    "source_task_id": m.get("source_task_id"),
                    "created_at": m.get("created_at"),
                }
                for m in motions
            ],
            "total": len(motions),
        }

    ctx.register_tool(
        name="agora_list_motions",
        toolset="agora",
        schema=_LIST_MOTIONS_SCHEMA,
        handler=_list_motions_handler,
        description="List active or closed discussions.",
        emoji="📋",
    )

    # --- Slash command: /agora ---
    def _agora_command_handler(raw_args: str) -> str | None:
        return _handle_agora_command(ctx, raw_args)

    ctx.register_command(
        "agora",
        handler=_agora_command_handler,
        description="Agora deliberation: /agora discuss <topic>",
        args_hint="<subcommand> [args]",
    )

    logger.info("Registered 4 agora tools + /agora command")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def _handle_raise_motion(ctx: Any, args: dict) -> dict:
    """Handle agora_raise_motion — create motion and run discussion."""
    from ..agora.storage import motions as db
    from ..agora.discussion.driver import DiscussionDriver
    title = args.get("title", "")
    description = args.get("description", "")
    context = args.get("context", "")
    blocking = args.get("blocking", False)
    participants = args.get("participants")
    rounds = args.get("rounds", 3)
    template_name = args.get("template")

    # Apply discussion template if specified
    if template_name:
        try:
            from ..agora.discussion.roles import DISCUSSION_TEMPLATES
            template = DISCUSSION_TEMPLATES.get(template_name)
            if template:
                if not participants:
                    participants = template.get("participants")
                rounds = template.get("rounds", rounds)
                suffix = template.get("prompt_suffix", "")
                if suffix:
                    description = f"{description}\n\n{suffix}".strip()
        except ImportError:
            pass

    # Detect source: if running inside a kanban task, attribute to agent
    source_task_id = os.environ.get("HERMES_KANBAN_TASK", "")
    source_profile = ctx.profile_name if hasattr(ctx, "profile_name") else "default"
    source = "agent" if source_task_id else "user"

    # Create the motion
    motion = db.create_motion(
        title=title,
        description=description + (f"\n\nContext: {context}" if context else ""),
        max_rounds=rounds,
        source=source,
        source_task_id=source_task_id or "",
        source_profile=source_profile,
        blocking=blocking,
        participants=participants,
    )

    motion_id = motion["id"]

    # If blocking, block the current kanban task
    if blocking and source_task_id:
        try:
            from hermes_cli import kanban_db
            conn = kanban_db.connect()
            try:
                kanban_db.block_task(
                    conn, source_task_id,
                    reason=f"Waiting for Agora motion {motion_id}",
                    kind="dependency",
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Failed to block source task: %s", exc)

    # Run the discussion asynchronously
    driver = DiscussionDriver(
        ctx,
        max_rounds=rounds,
        role_models=_load_role_models(ctx),
        role_profiles=_load_role_profiles(ctx),
    )

    # For non-blocking, run in background with error handling.
    # In CLI/chat mode the event loop exits after the tool returns,
    # so background tasks are silently dropped. Detect this by checking
    # if the running loop is the _run_async bridge (transient).
    if not blocking:
        _run_in_background = False
        try:
            loop = asyncio.get_running_loop()
            # Gateway runs a persistent asyncio loop. CLI chat -q uses
            # _run_async which creates a throwaway loop. Detect by checking
            # if there are other pending tasks (gateway has many).
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            _run_in_background = len(pending) > 3  # gateway has many tasks
        except RuntimeError:
            pass  # no running loop at all

        if _run_in_background:
            _start_background_discussion(driver, motion_id)
            return {
                "motion_id": motion_id,
                "title": title,
                "status": "discussing",
                "message": "Discussion started in background. Use agora_get_result to check outcome.",
                "participants": participants or ["architect", "developer", "reviewer"],
            }
        # CLI mode — run synchronously (blocking) to completion
        result = await driver.run(motion_id)
        return {
            "motion_id": motion_id,
            "title": title,
            "status": "closed",
            "decision": result.decision,
            "summary": result.summary,
            "action_items": result.action_items,
            "confidence": result.confidence,
            "created_tasks": result.created_tasks,
            "rounds_completed": result.rounds_completed,
        }

    # For blocking, run synchronously and return the result
    result = await driver.run(motion_id)
    return {
        "motion_id": motion_id,
        "title": title,
        "status": "closed",
        "decision": result.decision,
        "summary": result.summary,
        "action_items": result.action_items,
        "confidence": result.confidence,
        "created_tasks": result.created_tasks,
        "rounds_completed": result.rounds_completed,
    }


def _handle_agora_command(ctx: Any, raw_args: str) -> str | None:
    """Handle /agora slash command.

    Usage:
        /agora discuss <topic>       — start a discussion
        /agora list                   — list active discussions
        /agora show <motion_id>      — show discussion messages
        /agora result <motion_id>    — show discussion result
    """
    from ..agora.storage import motions as db
    from ..agora.discussion.driver import DiscussionDriver
    parts = raw_args.strip().split(None, 1)
    if not parts:
        return (
            "🏛️ **Agora** — multi-role deliberation\n\n"
            "Usage:\n"
            "  `/agora discuss <topic>` — start a discussion\n"
            "  `/agora list` — list active discussions\n"
            "  `/agora show <motion_id>` — show discussion messages\n"
            "  `/agora result <motion_id>` — show discussion result"
        )

    sub = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if sub == "discuss":
        if not arg:
            return "Usage: `/agora discuss <topic>`"

        # Create motion and run discussion
        motion = db.create_motion(
            title=arg,
            description="",
            max_rounds=3,
            source="user",
        )
        motion_id = motion["id"]

        # In slash command context, we can't run async discussion directly.
        # Create the motion and instruct the user to start it.
        return (
            f"🏛️ Discussion created: **{arg}**\n"
            f"Motion ID: `{motion_id}`\n"
            f"Participants: architect, developer, reviewer\n"
            f"Rounds: 3\n\n"
            f"To start the discussion, ask the agent:\n"
            f"  \"Use agora_raise_motion to discuss: {arg}\""
        )

    elif sub == "list":
        motions = db.list_motions(status_filter="all", limit=10)
        if not motions:
            return "No discussions yet. Use `/agora discuss <topic>` to start one."

        lines = ["📋 **Discussions**", ""]
        for m in motions:
            status_icon = "✅" if m["status"] == "closed" else "🔄"
            decision = f" → {m['decision']}" if m.get("decision") else ""
            source_tag = f" [{m['source']}]" if m.get("source") != "user" else ""
            lines.append(
                f"{status_icon} `{m['id']}` {m['title'][:60]}{decision}{source_tag}"
            )
        return "\n".join(lines)

    elif sub == "show":
        if not arg:
            return "Usage: `/agora show <motion_id>`"

        motion = db.get_motion(arg.strip())
        if motion is None:
            return f"Motion `{arg}` not found."

        messages = db.get_messages(arg.strip())
        if not messages:
            return f"Motion `{arg}` — no messages yet."

        lines = [
            f"🏛️ **{motion['title']}**",
            f"Status: {motion['status']} | Round: {motion['current_round']}/{motion['max_rounds']}",
            "",
        ]
        for m in messages:
            lines.append(f"**[{m['role']} R{m['round_num']}]** ({m['stance']})")
            lines.append(m["content"][:500])
            lines.append("")

        return "\n".join(lines)

    elif sub == "result":
        if not arg:
            return "Usage: `/agora result <motion_id>`"

        motion = db.get_motion(arg.strip())
        if motion is None:
            return f"Motion `{arg}` not found."

        if motion["status"] != "closed":
            return f"Motion `{arg}` is still {motion['status']}."

        lines = [
            f"✅ **{motion['title']}**",
            f"Decision: **{motion.get('decision', '?')}**",
            f"Summary: {motion.get('rationale', '')}",
            "",
            "**Action Items:**",
        ]
        for ai in motion.get("action_items", []):
            lines.append(f"  • {ai}")

        return "\n".join(lines)

    else:
        return f"Unknown subcommand: `{sub}`. Try: discuss, list, show, result"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _load_role_models(ctx: Any) -> dict[str, str]:
    """Read per-role model overrides from Hermes config.

    Config shape::

        plugins:
          entries:
            agora:
              agora:
                roles:
                  architect:
                    model: deepseekv4pro
                  developer:
                    model: astron-code-latest
    """
    try:
        from hermes_cli.config import load_config
        config = load_config() or {}
        agora_cfg = (
            config.get("plugins", {})
            .get("entries", {})
            .get("agora", {})
            .get("agora", {})
        )
        roles = agora_cfg.get("roles", {})
        return {
            role: cfg["model"]
            for role, cfg in roles.items()
            if isinstance(cfg, dict) and cfg.get("model")
        }
    except Exception:
        return {}


def _load_role_profiles(ctx: Any) -> dict[str, str]:
    """Read per-role profile overrides from Hermes config.

    Config shape::

        plugins:
          entries:
            agora:
              agora:
                roles:
                  architect:
                    profile: architect
                  developer:
                    profile: developer
    """
    try:
        from hermes_cli.config import load_config
        config = load_config() or {}
        agora_cfg = (
            config.get("plugins", {})
            .get("entries", {})
            .get("agora", {})
            .get("agora", {})
        )
        roles = agora_cfg.get("roles", {})
        return {
            role: cfg["profile"]
            for role, cfg in roles.items()
            if isinstance(cfg, dict) and cfg.get("profile")
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Background discussion runner — error callback + timeout
# ---------------------------------------------------------------------------

_DISCUSSION_TIMEOUT_SECONDS = 300  # 5 minutes max per discussion


def _start_background_discussion(driver: Any, motion_id: str) -> None:
    """Start a background discussion task with error handling and timeout.

    Errors are logged and the motion is marked as closed with an error
    status so the user can see something went wrong instead of polling
    forever.
    """
    async def _run_with_guard():
        from ..agora.storage import motions as db
        try:
            await asyncio.wait_for(
                driver.run(motion_id),
                timeout=_DISCUSSION_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error("Discussion %s timed out after %ds", motion_id, _DISCUSSION_TIMEOUT_SECONDS)
            try:
                db.update_motion_status(
                    motion_id,
                    status="closed",
                    decision="no_consensus",
                    rationale=f"Discussion timed out after {_DISCUSSION_TIMEOUT_SECONDS}s.",
                )
            except Exception:
                pass
        except Exception as exc:
            logger.error("Background discussion %s failed: %s", motion_id, exc, exc_info=True)
            try:
                db.update_motion_status(
                    motion_id,
                    status="closed",
                    decision="no_consensus",
                    rationale=f"Discussion failed with error: {exc}",
                )
            except Exception:
                pass

    task = asyncio.create_task(_run_with_guard())
    task.set_name(f"agora-discussion-{motion_id}")
    # Prevent the task from being garbage-collected if the event loop
    # doesn't hold a strong reference (rare but happens in some frameworks).
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
