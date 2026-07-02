"""Leader heartbeat loop — the single entry point for self-driving.

When the heartbeat fires (via cron job), this module:
  1. Finds all active projects with a heartbeat_member configured
  2. For each project, spawns the heartbeat member (leader) agent subprocess
  3. The agent uses project-specific session (--resume) for context isolation
     while sharing its MEMORY.md across projects (experience reuse)
  4. The agent follows its SOUL.md heartbeat protocol:
     - Check stuck/blocked tasks → decide to unblock/split/raise motion
     - Check if all tasks done → plan next phase or declare PROJECT_COMPLETE
     - Check stale motions → close them
  5. After spawn, checks the leader's output for PROJECT_COMPLETE

The Leader is the ONLY thing that needs external triggering.
Everything else (discussion, task creation, worker dispatch) flows
from the Leader's decisions.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from .utils import find_hermes_binary, now_iso, get_registry_dir, safe_name

logger = logging.getLogger(__name__)


def heartbeat(leader_name: str | None = None, project: str | None = None) -> dict:
    """Trigger a leader heartbeat.

    Can be called with either:
    - leader_name: specific leader profile to wake (searches all projects)
    - project: wake the heartbeat member for this project

    If neither is given, wakes ALL active projects' heartbeat members.

    Returns dict with spawn status.
    """
    from project_planner import list_projects, get_project, update_heartbeat_status, on_project_complete

    # Wake a specific project
    if project:
        proj = get_project(project)
        if proj is None:
            return {"error": f"Project '{project}' not found"}
        if proj.get("status") != "active":
            return {"error": f"Project '{project}' is not active (status={proj.get('status')})"}
        member = proj.get("heartbeat_member")
        if not member:
            return {"error": f"Project '{project}' has no heartbeat_member configured"}
        return _spawn_leader_agent(proj)

    # Wake a specific leader (find all projects using this leader)
    if leader_name:
        projects = [p for p in list_projects()
                    if p.get("status") == "active" and p.get("heartbeat_member") == leader_name]
        if not projects:
            return {"error": f"No active projects with heartbeat_member='{leader_name}'"}
        results = [_spawn_leader_agent(p) for p in projects]
        return {"status": "batch", "results": results}

    # Wake ALL active projects
    projects = [p for p in list_projects() if p.get("status") == "active" and p.get("heartbeat_member")]
    if not projects:
        return {"error": "No active projects with heartbeat members"}
    results = [_spawn_leader_agent(p) for p in projects]
    return {"status": "batch", "results": results}


def _spawn_leader_agent(project: dict) -> dict:
    """Spawn a leader agent subprocess for one heartbeat cycle.

    Non-blocking: spawns the process, writes output to a log file, and
    returns immediately with status="spawned". PROJECT_COMPLETE detection
    is done by checking the log file on subsequent runs.

    Per-project session isolation: the leader uses --resume with a
    project-specific session_id, so context doesn't bleed between
    projects. But MEMORY.md and skills are shared (experience reuse).
    """
    from project_planner import update_heartbeat_status, set_leader_session, get_leader_session
    from agora.worker_manager import get_worker, get_worker_session, update_worker_session

    project_name = project["name"]
    member_name = project.get("heartbeat_member", "")
    if not member_name:
        return {"error": f"Project '{project_name}' has no heartbeat_member"}

    worker = get_worker(member_name)
    if worker is None:
        return {"error": f"Heartbeat member '{member_name}' not found in worker registry"}

    profile_dir = worker.get("profile_dir", "")
    workdir = project.get("workdir", "")
    goal = project.get("goal", "")

    # Get project-specific session for context isolation
    session_id = get_leader_session(project_name)
    # Also check worker's per-project session map
    if not session_id:
        session_id = get_worker_session(member_name, project_name)

    # Check session size — rotate if too large
    try:
        from agora.session_manager import check_session_size, rotate_session
        size_info = check_session_size(member_name, session_id)
        if size_info.get("needs_rotation"):
            logger.info(
                "Leader '%s' session for project '%s' is large (count=%d) — rotating",
                member_name, project_name, size_info.get("message_count", 0),
            )
            rotate_session(member_name, member_name)
            session_id = None  # force fresh session
            set_leader_session(project_name, None)
    except Exception as exc:
        logger.debug("Session size check failed for %s/%s: %s", member_name, project_name, exc)

    # Build the heartbeat prompt
    prompt = _HEARTBEAT_PROMPT.format(
        leader_name=member_name,
        project=project_name,
        goal=goal or "(not specified)",
        workdir=workdir or "/root",
    )

    # Find hermes binary
    hermes_bin = find_hermes_binary()
    if not hermes_bin:
        return {"error": "Cannot find hermes binary"}

    # Build command — must include --yolo and --accept-hooks for unattended
    # operation. -Q gives quiet mode.
    cmd = [
        hermes_bin,
        "-p", member_name,
        "--yolo",
        "--accept-hooks",
        "chat", "-Q", "-q", prompt,
    ]

    # Resume project-specific session if available
    if session_id:
        cmd.extend(["--resume", session_id])

    # Environment
    env = dict(os.environ)
    profiles_root = Path(profile_dir).parent
    env["HERMES_HOME"] = str(profiles_root.parent)

    kanban_db = os.environ.get("HERMES_KANBAN_DB", "")
    if kanban_db:
        env["HERMES_KANBAN_DB"] = kanban_db

    if workdir and os.path.isabs(workdir):
        env["TERMINAL_CWD"] = workdir

    # Log file — per project
    log_path = get_registry_dir("projects") / f"heartbeat_{safe_name(project_name)}.log"

    try:
        log_fd = open(log_path, "a")
        proc = subprocess.Popen(
            cmd,
            stdout=log_fd,
            stderr=log_fd,
            env=env,
            cwd=workdir if workdir and os.path.isabs(workdir) else None,
            start_new_session=True,
        )

        # Update heartbeat record
        update_heartbeat_status(project_name, pid=proc.pid)

        logger.info(
            "Leader '%s' heartbeat spawned for project '%s' (PID %d, session=%s, log=%s)",
            member_name, project_name, proc.pid, session_id or "new", log_path,
        )
        return {
            "status": "spawned",
            "leader": member_name,
            "project": project_name,
            "pid": proc.pid,
            "session_id": session_id,
            "log": str(log_path),
        }
    except Exception as exc:
        logger.error("Failed to spawn leader '%s' for project '%s': %s", member_name, project_name, exc)
        return {"error": f"Failed to spawn leader: {exc}"}


def check_project_complete(project_name: str) -> bool:
    """Check if a project's leader has output PROJECT_COMPLETE in its log.

    Called by the heartbeat batch loop on subsequent runs to detect
    project completion from the previous spawn's output.
    """
    try:
        log_path = get_registry_dir("projects") / f"heartbeat_{safe_name(project_name)}.log"
        if not log_path.exists():
            return False

        # Read the last 5KB of the log
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 5120))
            tail = f.read().decode("utf-8", errors="replace")

        if "PROJECT_COMPLETE" in tail:
            from project_planner import on_project_complete
            on_project_complete(project_name)
            logger.info("Project '%s' complete detected from leader output", project_name)
            return True
    except Exception as exc:
        logger.debug("check_project_complete failed for %s: %s", project_name, exc)
    return False


# --------------------------------------------------------------------------- #
#  Heartbeat prompt                                                           #
# --------------------------------------------------------------------------- #

_HEARTBEAT_PROMPT = """\
Heartbeat wake-up for {leader_name}, heartbeat member of project '{project}'.

Project goal: {goal}
Project workdir: {workdir}

Follow your SOUL.md heartbeat protocol. Quick reference:

1. **Check stuck tasks**: Check for blocked tasks. For each:
   - Done but waiting on review -> mark done, create review task if needed
   - Hit limit or crashed -> unblock, split into smaller tasks, or adjust description
   - Blocked by design decision -> raise a motion with agora_raise_motion
   - Stuck too long -> unblock and reassign, or cancel

2. **Check failed tasks**: Handle any triaged tasks (analyze failure, fix, re-queue)

3. **Check progress**:
   - If running/todo > 0 -> do nothing, let workers continue
   - If all done (0 todo, 0 running, 0 blocked):
     -> Review the project goal: "{goal}"
     -> Check what has been accomplished so far (read files, check outputs)
     -> Is the goal achieved?
        - YES -> output PROJECT_COMPLETE with a summary of what was accomplished. Stop here.
        - NO -> plan the next phase. Create new kanban tasks directly with `hermes kanban add`.
          Assign each task to the appropriate team role.
          Only use agora_raise_motion if a direction decision needs team discussion.

4. **Check stale motions**: Close any motion discussing too long. Decide from the discussion so far.

Be decisive. Take action. Don't just report — DO things.
If you unblock a task, actually run the kanban command.
If you create tasks, actually run `hermes kanban add`.
If everything is fine, say "ALL_GOOD" and explain briefly what you checked.
If the project goal is achieved, say "PROJECT_COMPLETE" and explain why.
"""
