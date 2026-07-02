"""Leader heartbeat loop — the single entry point for self-driving.

When the heartbeat fires (via cron job), this module:
  1. Spawns a Leader agent subprocess (`hermes -p <leader> chat -q <prompt>`)
  2. The Leader agent follows its SOUL.md checklist:
     - Check stuck/blocked tasks → decide to unblock/split/raise motion
     - Check if all tasks done → raise motion for next phase
     - Check stale motions → close them
  3. The Leader has full agent capabilities (tools, LLM, file access)

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
    - leader_name: specific leader to wake up
    - project: wake up the leader for this project

    Returns dict with spawn status.
    """
    from .leader_manager import get_leader, get_leader_for_project, update_heartbeat, list_leaders

    # Find the leader
    if leader_name:
        leader = get_leader(leader_name)
        if leader is None:
            return {"error": f"Leader '{leader_name}' not found"}
    elif project:
        leader = get_leader_for_project(project)
        if leader is None:
            return {"error": f"No active leader for project '{project}'"}
    else:
        # Wake up ALL active leaders
        leaders = [l for l in list_leaders() if l.get("status") == "active"]
        if not leaders:
            return {"error": "No active leaders registered"}
        results = []
        for l in leaders:
            results.append(_spawn_leader_agent(l))
        return {"status": "batch", "results": results}

    # Spawn single leader
    return _spawn_leader_agent(leader)


def _spawn_leader_agent(leader: dict) -> dict:
    """Spawn a leader agent subprocess for one heartbeat cycle.

    Non-blocking: spawns the process, writes output to a log file, and
    returns immediately with status="spawned". PROJECT_COMPLETE detection
    is handled asynchronously by the heartbeat batch loop, which checks
    the log file on subsequent runs.

    The agent gets a prompt that tells it to:
    1. Check kanban board for stuck tasks
    2. Unblock/split/reassign as needed
    3. If all done, plan next phase (create tasks directly) or declare PROJECT_COMPLETE
    4. Check stale motions
    """
    name = leader["name"]
    project = leader.get("project", "")
    profile_dir = leader.get("profile_dir", "")
    workdir = ""
    goal = ""

    # Get project info from project registry
    try:
        proj_file = get_registry_dir("projects") / f"{safe_name(project)}.json"
        if proj_file.exists():
            proj = json.loads(proj_file.read_text())
            workdir = proj.get("workdir", "")
            goal = proj.get("goal", "")
    except Exception:
        pass

    # Check leader session size — rotate if too large to prevent bloat
    try:
        from .session_manager import check_session_size, rotate_session
        # Leaders don't store a session_id in the registry (they use
        # stateless chat calls), so pass None to use the heuristic
        # (motions messages + completed kanban tasks).
        size_info = check_session_size(name, None)
        if size_info.get("needs_rotation"):
            logger.info(
                "Leader '%s' session activity high (count=%d) — rotating",
                name, size_info.get("message_count", 0),
            )
            rotate_session(name, name)
    except Exception as exc:
        logger.debug("Leader session size check failed for %s: %s", name, exc)

    # Build the heartbeat prompt
    prompt = _HEARTBEAT_PROMPT.format(
        leader_name=name,
        project=project,
        goal=goal or "(not specified)",
        workdir=workdir or "/root",
    )

    # Find hermes binary
    hermes_bin = find_hermes_binary()
    if not hermes_bin:
        return {"error": "Cannot find hermes binary"}

    # Build command — must include --yolo and --accept-hooks for unattended
    # operation (otherwise the leader will prompt for approval on every shell
    # command and hang forever).  -Q gives quiet mode (only final response).
    # This is consistent with spawn_agent_speak in agent_spawn.py.
    cmd = [
        hermes_bin,
        "-p", name,
        "--yolo",           # bypass command approval (unattended)
        "--accept-hooks",   # auto-approve shell hooks
        "-Q",               # quiet mode: only final response + session info
        "chat", "-q", prompt,
    ]

    # Environment — set HERMES_HOME to the leader's profile
    env = dict(os.environ)
    profiles_root = Path(profile_dir).parent
    env["HERMES_HOME"] = str(profiles_root.parent)

    # Kanban DB
    kanban_db = os.environ.get("HERMES_KANBAN_DB", "")
    if kanban_db:
        env["HERMES_KANBAN_DB"] = kanban_db

    # Workdir
    if workdir and os.path.isabs(workdir):
        env["TERMINAL_CWD"] = workdir

    # Log file
    log_path = get_registry_dir("leaders") / f"heartbeat_{name}.log"

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
        from .leader_manager import update_heartbeat
        update_heartbeat(name, pid=proc.pid)

        logger.info(
            "Leader '%s' heartbeat spawned (PID %d, project=%s, log=%s)",
            name, proc.pid, project, log_path,
        )
        return {
            "status": "spawned",
            "leader": name,
            "project": project,
            "pid": proc.pid,
            "log": str(log_path),
        }
    except Exception as exc:
        logger.error("Failed to spawn leader '%s': %s", name, exc)
        return {"error": f"Failed to spawn leader: {exc}"}


def _on_project_complete(leader_name: str, project: str) -> None:
    """Handle project completion — stop the leader's cron job and update project status."""
    try:
        # Pause the leader's cron job
        from .leader_manager import get_leader
        leader = get_leader(leader_name)
        if leader:
            cron_id = leader.get("cron_job_id")
            if cron_id:
                hermes = find_hermes_binary()
                if hermes:
                    subprocess.run(
                        [hermes, "cron", "pause", cron_id],
                        capture_output=True, text=True, timeout=10,
                    )

        # Update project status
        try:
            registry_dir = get_registry_dir("projects")
            proj_file = registry_dir / f"{safe_name(project)}.json"
            if proj_file.exists():
                import json as _json
                proj = _json.loads(proj_file.read_text())
                proj["status"] = "completed"
                proj["completed_at"] = now_iso()
                proj_file.write_text(_json.dumps(proj, indent=2))
        except Exception:
            pass

        # Update leader status
        from .leader_manager import _leader_file
        lf = _leader_file(leader_name)
        if lf.exists():
            import json as _json
            data = _json.loads(lf.read_text())
            data["status"] = "completed"
            lf.write_text(_json.dumps(data, indent=2))

        logger.info("Project '%s' marked complete, leader '%s' cron paused", project, leader_name)
    except Exception as exc:
        logger.error("Failed to handle project completion: %s", exc)


# --------------------------------------------------------------------------- #
#  Heartbeat prompt                                                           #
# --------------------------------------------------------------------------- #

_HEARTBEAT_PROMPT = """\
Heartbeat wake-up for {leader_name}, team leader of project '{project}'.

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
