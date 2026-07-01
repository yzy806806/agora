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

    # --- Self-drive project management tools ---
    _register_project_tools(ctx)

    # --- Worker & team management tools ---
    _register_worker_tools(ctx)

    # --- Leader management tools ---
    _register_leader_tools(ctx)


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


# ---------------------------------------------------------------------------
# Self-drive project management tools
# ---------------------------------------------------------------------------

_START_PROJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Short project name (e.g. 'docmind')"},
        "workdir": {"type": "string", "description": "Absolute path to the project repository"},
        "goal": {"type": "string", "description": "High-level project goal", "default": ""},
        "initial_topic": {"type": "string", "description": "First discussion topic. If empty, planner auto-generates.", "default": ""},
        "max_rounds": {"type": "integer", "description": "Maximum planning rounds before stopping", "default": 10},
    },
    "required": ["name", "workdir"],
}

_STOP_PROJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Project name to stop"},
    },
    "required": ["name"],
}

_PROJECT_STATUS_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Project name (empty = list all)", "default": ""},
    },
}


def _register_project_tools(ctx: Any) -> None:
    """Register self-drive project management tools."""

    async def _start_project_handler(args: dict, **kwargs) -> dict:
        from ..project_planner import start_project
        name = args.get("name", "")
        workdir = args.get("workdir", "")
        goal = args.get("goal", "")
        initial_topic = args.get("initial_topic", "")
        max_rounds = args.get("max_rounds", 10)
        profile = ctx.profile_name if hasattr(ctx, "profile_name") else "coder"
        if not name or not workdir:
            return {"error": "name and workdir are required"}
        return start_project(
            project_name=name, workdir=workdir, goal=goal,
            initial_topic=initial_topic, profile=profile, max_rounds=max_rounds,
        )

    ctx.register_tool(
        name="agora_start_project",
        toolset="agora",
        schema=_START_PROJECT_SCHEMA,
        handler=_start_project_handler,
        is_async=True,
        description="Start a self-driving development project. Agora autonomously plans, discusses, and dispatches tasks until the goal is met.",
        emoji="🚀",
    )

    async def _stop_project_handler(args: dict, **kwargs) -> dict:
        from ..project_planner import stop_project
        name = args.get("name", "")
        if not name:
            return {"error": "name is required"}
        return stop_project(name)

    ctx.register_tool(
        name="agora_stop_project",
        toolset="agora",
        schema=_STOP_PROJECT_SCHEMA,
        handler=_stop_project_handler,
        is_async=True,
        description="Stop a self-driving project.",
        emoji="🛑",
    )

    def _project_status_handler(args: dict, **kwargs) -> dict:
        from ..project_planner import get_project, list_projects
        name = args.get("name", "")
        if name:
            data = get_project(name)
            if data is None:
                return {"error": f"Project '{name}' not found"}
            return data
        return {"projects": list_projects()}

    ctx.register_tool(
        name="agora_project_status",
        toolset="agora",
        schema=_PROJECT_STATUS_SCHEMA,
        handler=_project_status_handler,
        description="Check status of self-driving projects.",
        emoji="📊",
    )

    logger.info("Registered 3 project management tools")


# --------------------------------------------------------------------------- #
#  Worker & Team management tools                                             #
# --------------------------------------------------------------------------- #

_CREATE_WORKER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Profile name (lowercase alphanumeric, e.g. alice)"},
        "role": {
            "type": "string",
            "enum": ["architect", "developer", "reviewer", "tester", "devops"],
            "description": "Role template to use",
        },
        "clone_from": {"type": "string", "description": "Source profile to clone config from", "default": "coder"},
        "model": {"type": "string", "description": "Override model for this worker (optional)", "default": ""},
    },
    "required": ["name", "role"],
}

_LIST_WORKERS_SCHEMA = {"type": "object", "properties": {}}
_REMOVE_WORKER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Worker profile name to remove"},
        "delete_profile": {"type": "boolean", "description": "Also delete the Hermes profile directory", "default": True},
    },
    "required": ["name"],
}
_LIST_TEMPLATES_SCHEMA = {"type": "object", "properties": {}}
_CREATE_TEAM_SCHEMA = {
    "type": "object",
    "properties": {
        "team_name": {"type": "string", "description": "Unique team name"},
        "workers": {"type": "array", "items": {"type": "string"}, "description": "Worker profile names to include"},
        "project": {"type": "string", "description": "Project to bind this team to (optional)", "default": ""},
    },
    "required": ["team_name", "workers"],
}
_LIST_TEAMS_SCHEMA = {"type": "object", "properties": {}}
_REMOVE_TEAM_SCHEMA = {
    "type": "object",
    "properties": {"team_name": {"type": "string", "description": "Team name to remove"}},
    "required": ["team_name"],
}


def _register_worker_tools(ctx: Any) -> None:
    """Register worker and team management tools."""

    async def _create_worker_handler(args: dict, **kwargs) -> dict:
        from ..agora.worker_manager import create_worker
        return create_worker(
            name=args.get("name", ""),
            role=args.get("role", ""),
            clone_from=args.get("clone_from", "coder"),
            model=args.get("model", "") or None,
        )

    ctx.register_tool(
        name="agora_create_worker", toolset="agora", schema=_CREATE_WORKER_SCHEMA,
        handler=_create_worker_handler, is_async=True,
        description="Create a worker profile from a role template. Generates config, SOUL.md (identity), memory, and skills directory. The same worker can participate in multiple projects.",
        emoji="\U0001f464",
    )

    def _list_workers_handler(args: dict, **kwargs) -> dict:
        from ..agora.worker_manager import list_workers
        return {"workers": list_workers()}

    ctx.register_tool(
        name="agora_list_workers", toolset="agora", schema=_LIST_WORKERS_SCHEMA,
        handler=_list_workers_handler,
        description="List all registered Agora worker profiles.",
        emoji="\U0001f465",
    )

    async def _remove_worker_handler(args: dict, **kwargs) -> dict:
        from ..agora.worker_manager import remove_worker
        return remove_worker(args.get("name", ""), delete_profile=args.get("delete_profile", True))

    ctx.register_tool(
        name="agora_remove_worker", toolset="agora", schema=_REMOVE_WORKER_SCHEMA,
        handler=_remove_worker_handler, is_async=True,
        description="Remove a worker from the Agora registry and optionally delete the profile.",
        emoji="\U0001f5d1\ufe0f",
    )

    def _list_templates_handler(args: dict, **kwargs) -> dict:
        from ..agora.worker_templates import list_templates
        return {"templates": list_templates()}

    ctx.register_tool(
        name="agora_list_templates", toolset="agora", schema=_LIST_TEMPLATES_SCHEMA,
        handler=_list_templates_handler,
        description="List available role templates for creating workers.",
        emoji="\U0001f4cb",
    )

    async def _create_team_handler(args: dict, **kwargs) -> dict:
        from ..agora.team_manager import create_team
        return create_team(
            team_name=args.get("team_name", ""),
            worker_names=args.get("workers", []),
            project=args.get("project", "") or None,
        )

    ctx.register_tool(
        name="agora_create_team", toolset="agora", schema=_CREATE_TEAM_SCHEMA,
        handler=_create_team_handler, is_async=True,
        description="Create a team by selecting existing workers. A team is the assignee pool for a project. The same worker can be on multiple teams.",
        emoji="\U0001f91d",
    )

    def _list_teams_handler(args: dict, **kwargs) -> dict:
        from ..agora.team_manager import list_teams
        return {"teams": list_teams()}

    ctx.register_tool(
        name="agora_list_teams", toolset="agora", schema=_LIST_TEAMS_SCHEMA,
        handler=_list_teams_handler,
        description="List all registered teams.",
        emoji="\U0001f3c6",
    )

    async def _remove_team_handler(args: dict, **kwargs) -> dict:
        from ..agora.team_manager import remove_team
        return remove_team(args.get("team_name", ""))

    ctx.register_tool(
        name="agora_remove_team", toolset="agora", schema=_REMOVE_TEAM_SCHEMA,
        handler=_remove_team_handler, is_async=True,
        description="Remove a team from the registry.",
        emoji="\U0001f4a5",
    )

    logger.info("Registered 7 worker & team management tools")


# --------------------------------------------------------------------------- #
#  Leader management tools                                                    #
# --------------------------------------------------------------------------- #

_CREATE_LEADER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Profile name (e.g. frank)"},
        "project": {"type": "string", "description": "Project name this leader manages"},
        "clone_from": {"type": "string", "description": "Source profile to clone", "default": "coder"},
        "heartbeat_minutes": {"type": "integer", "description": "Heartbeat interval in minutes", "default": 15},
        "model": {"type": "string", "description": "Override model (optional)", "default": ""},
    },
    "required": ["name", "project"],
}

_LIST_LEADERS_SCHEMA = {"type": "object", "properties": {}}

_REMOVE_LEADER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Leader name to remove"},
        "delete_profile": {"type": "boolean", "default": True},
    },
    "required": ["name"],
}

_LEADER_HEARTBEAT_SCHEMA = {
    "type": "object",
    "properties": {
        "leader_name": {"type": "string", "description": "Specific leader to wake (optional)"},
        "project": {"type": "string", "description": "Wake leader for this project (optional). If both omitted, wakes all."},
    },
}


def _register_leader_tools(ctx: Any) -> None:
    """Register leader management tools."""

    async def _create_leader_handler(args: dict, **kwargs) -> dict:
        from ..agora.leader_manager import create_leader
        return create_leader(
            name=args.get("name", ""),
            project=args.get("project", ""),
            clone_from=args.get("clone_from", "coder"),
            heartbeat_minutes=args.get("heartbeat_minutes", 15),
            model=args.get("model", "") or None,
        )

    ctx.register_tool(
        name="agora_create_leader", toolset="agora", schema=_CREATE_LEADER_SCHEMA,
        handler=_create_leader_handler, is_async=True,
        description="Create a team leader for a project. Leader monitors progress, unblocks stuck tasks, and plans next phases. Gets woken up by heartbeat.",
        emoji="\U0001f451",
    )

    def _list_leaders_handler(args: dict, **kwargs) -> dict:
        from ..agora.leader_manager import list_leaders
        return {"leaders": list_leaders()}

    ctx.register_tool(
        name="agora_list_leaders", toolset="agora", schema=_LIST_LEADERS_SCHEMA,
        handler=_list_leaders_handler,
        description="List all registered team leaders.",
        emoji="\U0001f3af",
    )

    async def _remove_leader_handler(args: dict, **kwargs) -> dict:
        from ..agora.leader_manager import remove_leader
        return remove_leader(args.get("name", ""), delete_profile=args.get("delete_profile", True))

    ctx.register_tool(
        name="agora_remove_leader", toolset="agora", schema=_REMOVE_LEADER_SCHEMA,
        handler=_remove_leader_handler, is_async=True,
        description="Remove a leader from the registry.",
        emoji="\U0001f5d1\ufe0f",
    )

    async def _leader_heartbeat_handler(args: dict, **kwargs) -> dict:
        from ..agora.leader_loop import heartbeat
        return heartbeat(
            leader_name=args.get("leader_name", "") or None,
            project=args.get("project", "") or None,
        )

    ctx.register_tool(
        name="agora_leader_heartbeat", toolset="agora", schema=_LEADER_HEARTBEAT_SCHEMA,
        handler=_leader_heartbeat_handler, is_async=True,
        description="Trigger a leader heartbeat. The leader will check project health, unblock stuck tasks, and plan next steps. Wakes all leaders if no name/project specified.",
        emoji="\U0001f493",
    )

    logger.info("Registered 4 leader management tools")
