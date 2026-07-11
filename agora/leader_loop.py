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
        _rescue_stuck_motions(proj)
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
                _rescue_stuck_motions(p)
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
            _rescue_stuck_motions(p)
            results.append(_spawn_leader_agent(p))
    return {"status": "batch", "results": results}


def _cleanup_stale_discussion_states(db_module: Any) -> None:
    """Clean up discussion_state records for closed motions.

    Closed motions should not have 'discussing' or 'investigating' state
    lingering in the discussion_state table. This runs on every heartbeat
    to keep the table clean.
    """
    try:
        closed_motions = db_module.list_motions(status_filter="closed", limit=100)
        for m in closed_motions:
            state = db_module.get_discussion_state(m["id"])
            if state and state.get("current_state") != "closed":
                db_module.save_discussion_state(m["id"], current_state="closed")
                logger.debug("Cleaned stale state for closed motion %s", m["id"])
    except Exception as exc:
        logger.debug("Stale state cleanup failed: %s", exc)


def _rescue_stuck_motions(project: dict) -> None:
    """Find motions stuck in 'discussing' and re-spawn or close them.

    A motion can get stuck if:
    - It was created without chair/participants (old hook code)
    - spawn_discussion_driver failed silently
    - The discussion process crashed before or after writing messages

    For each stuck motion:
    - If no messages and no state → re-spawn (never started)
    - If has messages but driver is dead → re-spawn (crashed mid-discussion)
    - If no chair/participants can be resolved → close as error
    """
    try:
        from agora.storage import motions as db
        from agora.discussion.agent_spawn import spawn_discussion_driver

        project_name = project.get("name", "")
        if not project_name:
            return

        # Clean up stale discussion_state records for closed motions
        # (M4 fix: closed motions should not have 'discussing'/'investigating' state)
        _cleanup_stale_discussion_states(db)

        # Find discussing motions for this project
        motions = db.list_motions(status_filter="active", limit=50)
        for m in motions:
            if m.get("status") != "discussing":
                continue
            if m.get("project") and m["project"] != project_name:
                continue

            messages = db.get_messages(m["id"])

            # Check if a discussion_state exists — if it does, the driver
            # started but may have crashed.
            state = db.get_discussion_state(m["id"])

            if messages and state and state.get("last_action"):
                # Driver started, wrote messages, then crashed mid-discussion.
                # Re-spawn the driver so it can resume from where it left off.
                # The driver uses the discussion history to avoid repeating.
                logger.info(
                    "Rescuing crashed motion %s (%d messages, last_state=%s)",
                    m["id"], len(messages), state.get("current_state"),
                )
                # Fall through to re-spawn below
            elif messages and not (state and state.get("last_action")):
                # Has messages but no state record — unusual but treat as
                # in-progress (someone else may be driving it)
                continue
            elif not messages and state and state.get("last_action"):
                # Driver started but crashed before writing messages.
                # Skip to avoid re-spawning in a tight loop. Leader will
                # close it manually.
                continue
            # else: no messages, no state → never started, re-spawn below

            # Re-resolve chair and participants
            chair = m.get("chair", "")
            participants = m.get("participants")
            if isinstance(participants, str):
                try:
                    participants = json.loads(participants)
                except Exception:
                    participants = None

            if not chair:
                try:
                    from project_planner import get_heartbeat_member
                    chair = get_heartbeat_member(project_name) or ""
                except Exception:
                    pass

            if not participants:
                try:
                    from project_planner import get_project
                    from agora.team_manager import get_team_for_project, get_team
                    proj = get_project(project_name)
                    if proj and proj.get("team"):
                        team = get_team(proj["team"])
                        if team:
                            participants = [w["name"] for w in team.get("workers", [])]
                except Exception:
                    pass

            if not chair or not participants:
                logger.warning(
                    "Stuck motion %s: cannot resolve chair/participants — closing",
                    m["id"],
                )
                db.update_motion_status(m["id"], status="closed", decision="error")
                db.update_motion_state(m["id"], "closed")
                db.save_discussion_state(m["id"], current_state="closed")
                continue

            # Also skip empty-title motions — they have nothing to discuss
            if not m.get("title", "").strip():
                db.update_motion_status(m["id"], status="closed", decision="error")
                db.update_motion_state(m["id"], "closed")
                db.save_discussion_state(m["id"], current_state="closed")
                logger.warning("Closed empty-title motion %s", m["id"])
                continue

            workdir = project.get("workdir", "")
            logger.info(
                "Rescuing stuck motion %s (chair=%s, participants=%s)",
                m["id"], chair, participants,
            )
            spawn_discussion_driver(
                motion_id=m["id"],
                chair=chair,
                participants=participants,
                workdir=workdir,
                project_name=project_name,
            )
    except Exception as exc:
        logger.debug("rescue_stuck_motions failed: %s", exc)


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

    # Build the heartbeat prompt — context (goal, stop condition, team,
    # active motions) is in AGENTS.md which Hermes auto-injects into the
    # system prompt via TERMINAL_CWD. No need to duplicate it here.
    prompt = _HEARTBEAT_PROMPT.format(
        leader_name=member_name,
        project=project_name,
    )

    # Find hermes binary
    hermes_bin = find_hermes_binary()
    if not hermes_bin:
        return {"error": "Cannot find hermes binary"}

    # Build command — must include --yolo and --accept-hooks for unattended
    # operation. -Q gives quiet mode.
    # --toolsets agora is required so the leader can call agora_raise_motion,
    # agora_list_motions, etc. Without it, the leader's profile config only
    # loads the platform_toolsets.cli set (which doesn't include agora).
    cmd = [
        hermes_bin,
        "-p", member_name,
        "--yolo",
        "--accept-hooks",
        "--toolsets", "agora",
        "chat", "-Q", "-q", prompt,
    ]

    # Resume project-specific session if available
    if session_id:
        cmd.extend(["--resume", session_id])

    # Environment — do NOT override HERMES_HOME here.
    # The -p flag makes Hermes set HERMES_HOME to the profile directory
    # (~/.hermes/profiles/<name>/), giving each worker isolated memory,
    # skills, and sessions. Overriding it back to the global root would
    # destroy that isolation (all workers sharing one MEMORY.md, one
    # skills pool, one sessions DB).
    env = dict(os.environ)

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

Read AGENTS.md in the project workdir for current goal, stop condition, \
team members, and active discussions.

Check current status and take action per your SOUL.md heartbeat protocol. \
If everything is running fine, say "ALL_GOOD" with a brief summary. \
If tasks are all done, assess the project and plan the next valuable work. \
Only output "PROJECT_COMPLETE" if you've confirmed twice that the stop \
condition is met and there's truly nothing left to do.
"""
