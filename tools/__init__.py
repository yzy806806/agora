"""Agora tools — registered with Hermes plugin system.

Tools:
  - agora_raise_motion    — agent/user initiates a discussion
  - agora_get_messages    — read discussion messages
  - agora_get_result      — read closed discussion result
  - agora_list_motions    — list active/closed discussions
  - agora_start_project   — start a self-driving project
  - agora_stop_project    — stop a project
  - agora_project_status  — check project status
  - agora_create_worker   — create a worker profile
  - agora_list_workers    — list workers
  - agora_remove_worker   — remove a worker
  - agora_list_templates  — list role templates
  - agora_create_team     — create a team
  - agora_list_teams      — list teams
  - agora_remove_team     — remove a team
"""
from __future__ import annotations

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
            "items": { "type": "string" },
            "description": "Worker profile names to participate (auto-detected from team if empty)",
        },
        "chair": {
            "type": "string",
            "description": "Worker profile name to act as chair (leader). If omitted, the system will auto-resolve from the project team.",
            "default": "",
        },
        "max_steps": {
            "type": "integer",
            "default": 30,
            "description": "Maximum discussion steps before the chair forces consensus",
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

    # --- Tool: agora_raise_motion ---
    async def _raise_motion_handler(args: dict, **kwargs) -> dict:
        return await _handle_raise_motion(ctx, args)

    ctx.register_tool(
        name="agora_raise_motion",
        toolset="agora",
        schema=_RAISE_MOTION_SCHEMA,
        handler=_raise_motion_handler,
        is_async=True,
        description="Raise a motion for team discussion. Creates the motion and returns the motion_id. The discussion is triggered by the leader heartbeat or the plugin API.",
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


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def _handle_raise_motion(ctx: Any, args: dict) -> dict:
    """Handle agora_raise_motion — create a motion for team discussion.

    In v2.0, this tool only CREATES the motion. The discussion driver is
    spawned separately (by the Leader heartbeat or the Dashboard API).
    The calling agent can continue working — it will see the discussion
    result in its MEMORY.md when the discussion completes.
    """
    from ..agora.storage import motions as db
    title = args.get("title", "")
    description = args.get("description", "")
    context = args.get("context", "")
    blocking = args.get("blocking", False)
    participants = args.get("participants")
    chair = args.get("chair", "")
    max_steps = args.get("max_steps", 30)
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
                suffix = template.get("prompt_suffix", "")
                if suffix:
                    description = f"{description}\n\n{suffix}".strip()
        except ImportError:
            pass

    # Detect source: if running inside a kanban task, attribute to agent
    source_task_id = os.environ.get("HERMES_KANBAN_TASK", "")
    source_profile = ctx.profile_name if hasattr(ctx, "profile_name") else "default"
    source = "agent" if source_task_id else "user"

    # Try to auto-resolve participants and chair from the project
    if not participants or not chair:
        try:
            from project_planner import get_heartbeat_member, get_project
            from agora.team_manager import get_team_for_project, get_team
            from hermes_cli import kanban_db

            # 1. Resolve project name from source task
            resolved_project = ""
            conn = kanban_db.connect()
            try:
                if source_task_id:
                    task = kanban_db.get_task(conn, source_task_id)
                    if task and task.tenant:
                        resolved_project = task.tenant.replace("agora-", "")
            finally:
                conn.close()

            # 2. If no project from task, try the source_profile's active project
            if not resolved_project:
                try:
                    from project_planner import list_projects
                    for p in list_projects():
                        if p.get("status") == "active":
                            resolved_project = p["name"]
                            break
                except Exception:
                    pass

            # 3. Get heartbeat_member as default chair
            if resolved_project and not chair:
                chair = get_heartbeat_member(resolved_project) or ""

            # 4. Get team participants + default max_steps
            if resolved_project and (not participants or max_steps == 30):
                proj = get_project(resolved_project)
                if proj and proj.get("team"):
                    team = get_team(proj["team"])
                    if team:
                        if not participants:
                            participants = [w["name"] for w in team.get("workers", [])]
                        if max_steps == 30 and team.get("default_max_steps"):
                            max_steps = team["default_max_steps"]
        except Exception:
            pass

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
        chair=chair,
        max_steps=max_steps,
        project=resolved_project if 'resolved_project' in dir() else "",
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

    # Event-driven discussion trigger: spawn the discussion driver immediately
    # if we know both the chair and participants.  This avoids waiting up to
    # 15 minutes for the leader heartbeat to pick it up.
    spawn_status = None
    if chair and participants:
        try:
            from ..agora.discussion.agent_spawn import spawn_discussion_driver

            # Resolve workdir from the project registry if possible
            spawn_workdir = ""
            spawn_project = ""
            try:
                from ..agora.utils import get_registry_dir, safe_name
                if source_task_id:
                    from hermes_cli import kanban_db
                    conn = kanban_db.connect()
                    try:
                        task = kanban_db.get_task(conn, source_task_id)
                        if task and task.tenant:
                            spawn_project = task.tenant
                    finally:
                        conn.close()
                if spawn_project:
                    proj_file = get_registry_dir("projects") / f"{safe_name(spawn_project)}.json"
                    if proj_file.exists():
                        import json as _json
                        proj = _json.loads(proj_file.read_text())
                        spawn_workdir = proj.get("workdir", "")
            except Exception:
                pass

            spawn_status = spawn_discussion_driver(
                motion_id=motion_id,
                chair=chair,
                participants=participants,
                workdir=spawn_workdir,
                project_name=spawn_project,
                max_steps=max_steps,
            )
            logger.info(
                "Event-driven discussion spawned for motion %s: %s",
                motion_id, spawn_status.get("status"),
            )
        except Exception as exc:
            logger.warning(
                "Failed to spawn discussion driver for motion %s: %s "
                "(motion created, will be picked up by leader heartbeat)",
                motion_id, exc,
            )

    # Build the return message
    if spawn_status and spawn_status.get("status") == "spawned":
        msg = (
            "Motion created and discussion driver spawned immediately. "
            f"Chair: {chair}. Log: {spawn_status.get('log', '')}. "
            "Use agora_get_result to check the outcome."
        )
    elif chair and participants:
        msg = (
            "Motion created. Discussion driver spawn failed — will be "
            "triggered by the leader heartbeat. Use agora_get_result to check."
        )
    else:
        msg = (
            "Motion created. The discussion will be triggered by the leader "
            "heartbeat or the plugin API. Use agora_get_result to check the outcome."
        )

    return {
        "motion_id": motion_id,
        "title": title,
        "status": "discussing",
        "chair": chair or "(unassigned — will be resolved by leader heartbeat)",
        "participants": participants or ["architect", "developer", "reviewer"],
        "max_steps": max_steps,
        "message": msg,
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

        # Create motion — discussion will be triggered by leader heartbeat
        # or plugin API, not here.
        motion = db.create_motion(
            title=arg,
            description="",
            max_rounds=3,
            source="user",
        )
        motion_id = motion["id"]

        chair = motion.get("chair", "")
        participants = motion.get("participants", ["architect", "developer", "reviewer"])

        return (
            f"🏛️ Discussion created: **{arg}**\n"
            f"Motion ID: `{motion_id}`\n"
            f"Chair: {chair or '(unassigned)'}\n"
            f"Participants: {', '.join(participants)}\n\n"
            f"To start the discussion, ask the agent:\n"
            f"  \"Use agora_raise_motion to discuss: {arg}\"\n"
            f"Or trigger via the Dashboard API."
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
        "heartbeat_member": {"type": "string", "description": "Worker name to wake on heartbeat (usually a leader). If omitted, no heartbeat is scheduled.", "default": ""},
        "heartbeat_minutes": {"type": "integer", "description": "Heartbeat interval in minutes", "default": 15},
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
        heartbeat_member = args.get("heartbeat_member", "") or None
        heartbeat_minutes = args.get("heartbeat_minutes", 15)
        profile = ctx.profile_name if hasattr(ctx, "profile_name") else "coder"
        if not name or not workdir:
            return {"error": "name and workdir are required"}
        return start_project(
            project_name=name, workdir=workdir, goal=goal,
            initial_topic=initial_topic, profile=profile, max_rounds=max_rounds,
            heartbeat_member=heartbeat_member, heartbeat_minutes=heartbeat_minutes,
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
    "properties": {
        "team_name": {"type": "string", "description": "Team name to remove"},
    },
    "required": ["team_name"],
}


def _register_worker_tools(ctx: Any) -> None:
    """Register worker and team management tools."""

    async def _create_worker_handler(args: dict, **kwargs) -> dict:
        from ..agora.worker_manager import create_worker
        return create_worker(
            name=args.get("name", ""),
            role=args.get("role", ""),
            clone_from=args.get("clone_from"),  # None by default — copy global config.yaml
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
