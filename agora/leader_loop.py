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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

    The agent gets a prompt that tells it to:
    1. Check kanban board for stuck tasks
    2. Unblock/split/reassign as needed
    3. If all done, raise a motion for next phase
    4. Check stale motions
    """
    name = leader["name"]
    project = leader.get("project", "")
    profile_dir = leader.get("profile_dir", "")
    workdir = ""

    # Get project workdir from project registry
    try:
        kanban_db = os.environ.get("HERMES_KANBAN_DB", "")
        if kanban_db:
            registry_dir = Path(kanban_db).parent / "agora" / "projects"
        else:
            registry_dir = Path.home() / ".hermes" / "agora" / "projects"
        proj_file = registry_dir / f"{project.replace('/', '-').replace(' ', '_')}.json"
        if proj_file.exists():
            import json as _json
            proj = _json.loads(proj_file.read_text())
            workdir = proj.get("workdir", "")
    except Exception:
        pass

    # Build the heartbeat prompt
    prompt = _HEARTBEAT_PROMPT.format(
        leader_name=name,
        project=project,
        workdir=workdir or "/root",
    )

    # Find hermes binary
    hermes_bin = _find_hermes_binary()
    if hermes_bin is None:
        return {"error": "Cannot find hermes binary"}

    # Build command
    cmd = [hermes_bin, "-p", name, "chat", "-q", prompt]

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
    from .leader_manager import _registry_dir
    log_path = _registry_dir() / f"heartbeat_{name}.log"

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


def _find_hermes_binary() -> str | None:
    candidates = [
        os.environ.get("HERMES_BIN", ""),
        "/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes",
        "/root/.hermes/hermes-agent/venv/bin/hermes",
        "/usr/local/bin/hermes",
        "/usr/bin/hermes",
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    import shutil
    found = shutil.which("hermes")
    return found


# --------------------------------------------------------------------------- #
#  Heartbeat prompt                                                           #
# --------------------------------------------------------------------------- #

_HEARTBEAT_PROMPT = """\
Heartbeat wake-up for {leader_name}, team leader of project '{project}'.

Follow your SOUL.md heartbeat protocol. Here's a quick reference:

1. **Check stuck tasks**: Run `hermes kanban list --status blocked`
   For each blocked task, read its comments and decide:
   - Work is done but waiting for review → mark as done, optionally create a review task
   - Hit iteration limit or crashed → unblock, split into smaller tasks, or adjust description
   - Blocked by design decision → raise a motion with agora_raise_motion
   - Stuck too long → unblock and reassign, or cancel

2. **Check triage**: Run `hermes kanban list --status triage`
   Handle any triaged tasks (analyze failure, fix description, re-queue)

3. **Check progress**: Run `hermes kanban stats`
   - If running/todo > 0 → do nothing, let workers continue
   - If all done (0 todo, 0 running, 0 blocked) → raise a motion for next phase
   - If project goal achieved → say "PROJECT_COMPLETE" with summary

4. **Check stale motions**: Run `hermes agora list --status active`
   Close any motion that's been discussing too long.

Project workdir: {workdir}
You can use `cd {workdir}` to inspect code, run git log, run tests, etc.

Be decisive. Take action. Don't just report — DO things.
If you unblock a task, actually run the kanban command to unblock it.
If you raise a motion, actually call agora_raise_motion.
If everything is fine, say "ALL_GOOD" and explain briefly what you checked.
"""
