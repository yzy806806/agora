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

    Before spawning, checks if the previous heartbeat output contained
    PROJECT_COMPLETE. If so, calls on_project_complete to stop the project.

    Returns dict with spawn status.
    """
    from project_planner import list_projects, get_project, update_heartbeat_status, on_project_complete

    # Wake a specific project
    if project:
        # Check if previous heartbeat signaled completion
        check_project_complete(project)

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
        results = []
        for p in projects:
            check_project_complete(p["name"])
            if p.get("status") == "active":  # may have been completed by check
                results.append(_spawn_leader_agent(p))
        return {"status": "batch", "results": results}

    # Wake ALL active projects
    projects = [p for p in list_projects() if p.get("status") == "active" and p.get("heartbeat_member")]
    if not projects:
        return {"error": "No active projects with heartbeat members"}
    results = []
    for p in projects:
        check_project_complete(p["name"])
        if p.get("status") == "active":  # may have been completed by check
            results.append(_spawn_leader_agent(p))
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

    # Refresh AGENTS.md so the leader and workers always see current team
    try:
        from project_planner import update_project_agents_md
        update_project_agents_md(project_name)
    except Exception:
        pass

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

    Called by the heartbeat() function before spawning a new leader agent.
    Uses a completion counter to require TWO consecutive PROJECT_COMPLETE
    signals before actually stopping the project. This prevents premature
    shutdown when the leader finds temporary idle periods.

    The first PROJECT_COMPLETE increments the counter and lets the heartbeat
    continue (so the leader gets another chance to find work). The second
    consecutive one triggers on_project_complete.
    """
    try:
        from project_planner import get_project, on_project_complete

        proj = get_project(project_name)
        if proj is None or proj.get("status") != "active":
            return False

        log_path = get_registry_dir("projects") / f"heartbeat_{safe_name(project_name)}.log"
        if not log_path.exists():
            return False

        # Check if this heartbeat's output contained PROJECT_COMPLETE.
        # We track the last-seen position so we only detect NEW occurrences.
        last_pos = proj.get("complete_check_pos", 0)
        current_size = log_path.stat().st_size

        if current_size <= last_pos:
            # No new output since last check
            return False

        # Read only the new portion
        with open(log_path, "rb") as f:
            f.seek(last_pos)
            new_content = f.read().decode("utf-8", errors="replace")

        # Update the check position regardless
        _update_complete_check_pos(project_name, current_size)

        if "PROJECT_COMPLETE" not in new_content:
            # Reset counter — leader is actively working
            if proj.get("complete_count", 0) > 0:
                _update_complete_count(project_name, 0)
            return False

        # PROJECT_COMPLETE found in new output
        count = proj.get("complete_count", 0) + 1
        _update_complete_count(project_name, count)

        if count >= 2:
            logger.info(
                "Project '%s' complete: %d consecutive PROJECT_COMPLETE signals",
                project_name, count,
            )
            on_project_complete(project_name)
            return True
        else:
            logger.info(
                "Project '%s': PROJECT_COMPLETE #%d (need 2 to stop) — giving leader another chance",
                project_name, count,
            )
            return False

    except Exception as exc:
        logger.debug("check_project_complete failed for %s: %s", project_name, exc)
    return False


def _update_complete_count(project_name: str, count: int) -> None:
    """Update the consecutive PROJECT_COMPLETE counter for a project."""
    try:
        from project_planner import get_project
        pf = get_registry_dir("projects") / f"{safe_name(project_name)}.json"
        if not pf.exists():
            return
        data = json.loads(pf.read_text())
        data["complete_count"] = count
        pf.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def _update_complete_check_pos(project_name: str, pos: int) -> None:
    """Update the last-checked log position for PROJECT_COMPLETE detection."""
    try:
        pf = get_registry_dir("projects") / f"{safe_name(project_name)}.json"
        if not pf.exists():
            return
        data = json.loads(pf.read_text())
        data["complete_check_pos"] = pos
        pf.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


# --------------------------------------------------------------------------- #
#  Heartbeat prompt                                                           #
# --------------------------------------------------------------------------- #

_HEARTBEAT_PROMPT = """\
Heartbeat wake-up for {leader_name}, project '{project}'.

Goal: {goal}
Workdir: {workdir}

Check current status and take action per your SOUL.md heartbeat protocol.
If everything is running fine, say "ALL_GOOD" with a brief summary.
If tasks are all done, assess the project and plan the next valuable work.
Only output "PROJECT_COMPLETE" if you've confirmed twice that there's truly nothing left to do.
"""
