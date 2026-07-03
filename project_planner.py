"""Self-driving project loop — project lifecycle + heartbeat management.

In this architecture, the Leader IS the planner. A leader is just a worker
created from the "leader" template. Heartbeat scheduling lives on the
*project*, not the profile — so the same leader profile can manage multiple
projects with independent heartbeat intervals and sessions, while sharing
a single MEMORY.md (experience).

This module handles:
  - start_project: register project, configure heartbeat
  - stop_project: stop a project, pause heartbeat
  - get/list projects for dashboard display
  - heartbeat management: create/pause/resume/trigger/update cron
  - on_task_completed: hook entry point (checks if project is complete)
  - PROJECT_COMPLETE detection from leader stdout
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from agora.utils import get_registry_dir, safe_name, find_hermes_binary, now_iso

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  Project registry                                                           #
# --------------------------------------------------------------------------- #

def _project_file(project_name: str) -> Path:
    return get_registry_dir("projects") / f"{safe_name(project_name)}.json"


def _ensure_project_board(project_name: str) -> str:
    """Create a kanban board name for the project.

    Returns the board name (used as kanban tenant for project isolation).
    """
    board_name = f"agora-{safe_name(project_name)}"
    logger.info("Project board ensured: %s", board_name)
    return board_name


def update_project_agents_md(project_name: str) -> dict:
    """Write/update AGENTS.md in the project workdir with team info.

    This file is auto-loaded by Hermes into every worker's system prompt
    (via TERMINAL_CWD context file scanning). It gives workers awareness
    of their team members, roles, and project context without requiring
    any changes to Hermes itself.

    Called on:
    - start_project (initial write)
    - leader heartbeat (refresh — members may have been added/removed)
    """
    proj = get_project(project_name)
    if proj is None:
        return {"error": f"Project '{project_name}' not found"}

    workdir = proj.get("workdir", "")
    if not workdir or not os.path.isabs(workdir):
        return {"skipped": "no valid workdir"}

    workdir_path = Path(workdir)
    if not workdir_path.exists():
        return {"skipped": "workdir does not exist"}

    # Gather team info
    team_name = proj.get("team", "")
    members = []
    if team_name:
        try:
            from agora.team_manager import get_team
            team = get_team(team_name)
            if team:
                for w in team.get("workers", []):
                    members.append({
                        "name": w["name"],
                        "role": w.get("role", "unknown"),
                        "display_name": w.get("display_name", w["role"]),
                    })
        except Exception as exc:
            logger.warning("Failed to get team info for AGENTS.md: %s", exc)

    # Build the AGENTS.md content
    lines = [
        "# Project Context",
        "",
        f"**Project:** {project_name}",
        f"**Goal:** {proj.get('goal', '(not specified)')}",
        f"**Status:** {proj.get('status', 'unknown')}",
        "",
    ]

    if proj.get("heartbeat_member"):
        lines.append(f"**Heartbeat Member:** {proj['heartbeat_member']} (woken every {proj.get('heartbeat_minutes', '?')} min)")
        lines.append("")

    if members:
        lines.append("## Team Members")
        lines.append("")
        lines.append("| Name | Role |")
        lines.append("|------|------|")
        for m in members:
            is_hb = " (heartbeat)" if m["name"] == proj.get("heartbeat_member") else ""
            lines.append(f"| {m['name']}{is_hb} | {m['display_name']} |")
        lines.append("")
        lines.append("When creating follow-up tasks, assign them to the appropriate team member above.")
        lines.append("Use `hermes profile list` to verify member availability.")
        lines.append("")

    # Project-specific instructions
    lines.append("## Workflow")
    lines.append("")
    lines.append("1. Check `hermes kanban list` for your assigned tasks.")
    lines.append("2. Use `kanban_show()` to read task details.")
    lines.append("3. After completing a task, use `kanban_complete(summary=..., metadata=...)`.")
    lines.append("4. If blocked, use `kanban_block(reason=...)` with a clear explanation.")
    lines.append("5. For design decisions that need team input, use `agora_raise_motion`.")
    lines.append("")

    agents_path = workdir_path / "AGENTS.md"
    try:
        agents_path.write_text("\n".join(lines))
        logger.info("AGENTS.md written to %s for project '%s'", agents_path, project_name)
        return {"status": "updated", "path": str(agents_path), "members": len(members)}
    except Exception as exc:
        logger.warning("Failed to write AGENTS.md: %s", exc)
        return {"error": str(exc)}


# --------------------------------------------------------------------------- #
#  Heartbeat cron management                                                  #
# --------------------------------------------------------------------------- #

def _create_heartbeat_cron(project_name: str, minutes: int) -> str | None:
    """Create a Hermes cron job that triggers heartbeat for a project.

    Returns the cron job ID, or None on failure.
    """
    hermes = find_hermes_binary()
    schedule = f"every {minutes}m"
    job_name = f"heartbeat-{safe_name(project_name)}"

    _ensure_heartbeat_script()

    cmd = [
        hermes, "cron", "create", schedule,
        "--name", job_name,
        "--no-agent",
        "--script", "leader_heartbeat.sh",
        "--deliver", "local",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=15,
            env={**os.environ},
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "Created job:" in line:
                    job_id = line.split("Created job:")[1].strip().split()[0]
                    logger.info("Cron job %s created for project %s", job_id, project_name)
                    return job_id
        logger.warning("Failed to create cron job: %s", result.stderr or result.stdout)
    except Exception as exc:
        logger.warning("Failed to create cron job: %s", exc)
    return None


def _ensure_heartbeat_script() -> None:
    """Ensure the leader_heartbeat.sh script exists in ~/.hermes/scripts/."""
    try:
        kanban_db = os.environ.get("HERMES_KANBAN_DB", "")
        if kanban_db:
            scripts_dir = Path(kanban_db).parent / "scripts"
        else:
            scripts_dir = Path.home() / ".hermes" / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        script_path = scripts_dir / "leader_heartbeat.sh"
        if script_path.exists():
            return

        script_content = """#!/bin/bash
# Leader heartbeat — called by Hermes cron scheduler.
# Wakes ALL active project leaders. Each leader follows its SOUL.md protocol.
# To change a specific project's interval: hermes cron edit <job_id> --schedule "30m"
# To pause: hermes cron pause heartbeat-<project_name>
# To resume: hermes cron resume heartbeat-<project_name>

export HERMES_KANBAN_DB="${HERMES_KANBAN_DB:-/root/.hermes/kanban.db}"

PYTHON=""
for p in /usr/local/lib/hermes-agent/venv/bin/python3 /home/ubuntu/.hermes/hermes-agent/venv/bin/python3 /usr/bin/python3; do
    [ -x "$p" ] && PYTHON="$p" && break
done
[ -z "$PYTHON" ] && PYTHON=python3

# Search for the agora plugin directory — must contain agora/ submodule
PLUGIN=""
for d in /root/agora /root/.hermes/profiles/coder/plugins/agora /root/.hermes/plugins/agora; do
    [ -d "$d/agora" ] && PLUGIN="$d" && break
done

$PYTHON -c "
import sys, json, os
sys.path.insert(0, os.environ.get('AGORA_PLUGIN_PATH', '$PLUGIN'))
from agora.leader_loop import heartbeat
result = heartbeat()
print(json.dumps(result, indent=2))
" 2>&1 | tail -10
"""
        script_path.write_text(script_content)
        script_path.chmod(0o755)
        logger.info("Heartbeat script created at %s", script_path)
    except Exception as exc:
        logger.warning("Failed to create heartbeat script: %s", exc)


def _remove_heartbeat_cron(cron_id: str) -> None:
    """Remove a Hermes cron job by ID."""
    hermes = find_hermes_binary()
    try:
        subprocess.run(
            [hermes, "cron", "remove", cron_id],
            capture_output=True, text=True, timeout=10,
        )
        logger.info("Cron job %s removed", cron_id)
    except Exception as exc:
        logger.warning("Failed to remove cron job %s: %s", cron_id, exc)


# --------------------------------------------------------------------------- #
#  Public API — project lifecycle                                             #
# --------------------------------------------------------------------------- #

def start_project(
    project_name: str,
    workdir: str,
    goal: str = "",
    initial_topic: str = "",
    profile: str = "coder",
    max_rounds: int = 10,
    team: str | None = None,
    heartbeat_member: str | None = None,
    heartbeat_minutes: int = 15,
) -> dict:
    """Register a project for self-driving development.

    Args:
        project_name:      Short name (e.g. "docmind")
        workdir:           Absolute path to the project repo
        goal:              High-level goal
        initial_topic:     First discussion topic (auto-generated if empty)
        profile:           Hermes profile to use for workers
        max_rounds:        Maximum planning rounds before stopping
        team:              Team name for assignee routing
        heartbeat_member:  Worker name to wake on heartbeat (usually a leader)
        heartbeat_minutes: Heartbeat interval in minutes

    Returns:
        dict with status and project info
    """
    pf = _project_file(project_name)
    board_name = _ensure_project_board(project_name)

    # Validate heartbeat_member if provided
    if heartbeat_member:
        from agora.worker_manager import get_worker
        worker = get_worker(heartbeat_member)
        if worker is None:
            return {"error": f"Heartbeat member '{heartbeat_member}' not found in worker registry"}

    data = {
        "name": project_name,
        "workdir": workdir,
        "goal": goal,
        "profile": profile,
        "max_rounds": max_rounds,
        "current_round": 0,
        "status": "active",
        "created_at": now_iso(),
        "initial_topic": initial_topic,
        "team": team,
        "board": board_name,
        # Heartbeat config — lives on the project, not the profile
        "heartbeat_member": heartbeat_member,
        "heartbeat_minutes": heartbeat_minutes,
        "heartbeat_cron_id": None,
        "leader_session_id": None,  # per-project session for the heartbeat member
        "last_heartbeat_at": None,
        "last_heartbeat_pid": None,
    }

    # Create cron job for heartbeat if member is specified
    if heartbeat_member:
        cron_id = _create_heartbeat_cron(project_name, heartbeat_minutes)
        if cron_id:
            data["heartbeat_cron_id"] = cron_id

    pf.write_text(json.dumps(data, indent=2))
    logger.info(
        "Project %s started: %s (heartbeat=%s, member=%s, cron=%s)",
        project_name, workdir, heartbeat_minutes, heartbeat_member,
        data.get("heartbeat_cron_id"),
    )

    # If team is specified, bind team to project and add ALL team members
    # to the project's worker list (not just the heartbeat member).
    if team:
        try:
            from agora.team_manager import _bind_team_to_project, get_team
            _bind_team_to_project(team, project_name)
            # Add project to every team member's projects list
            tm = get_team(team)
            if tm:
                for w in tm.get("workers", []):
                    _add_project_to_worker(w["name"], project_name)
        except Exception as exc:
            logger.warning("Failed to bind team to project: %s", exc)

    # Also add heartbeat_member if not in a team
    if heartbeat_member and not team:
        _add_project_to_worker(heartbeat_member, project_name)

    # Write AGENTS.md to workdir so workers auto-load team context
    update_project_agents_md(project_name)

    return {"status": "started", "project": data}


def stop_project(project_name: str) -> dict:
    """Stop a self-driving project and pause its heartbeat."""
    pf = _project_file(project_name)
    if not pf.exists():
        return {"error": f"Project '{project_name}' not found"}
    data = json.loads(pf.read_text())

    # Pause cron job
    cron_id = data.get("heartbeat_cron_id")
    if cron_id:
        _remove_heartbeat_cron(cron_id)

    data["status"] = "stopped"
    pf.write_text(json.dumps(data, indent=2))
    logger.info("Project %s stopped", project_name)
    return {"status": "stopped", "project": data}


def get_project(project_name: str) -> dict | None:
    """Get project registry data."""
    pf = _project_file(project_name)
    if not pf.exists():
        return None
    return json.loads(pf.read_text())


def list_projects() -> list[dict]:
    """List all registered projects."""
    d = get_registry_dir("projects")
    projects = []
    for f in d.glob("*.json"):
        try:
            projects.append(json.loads(f.read_text()))
        except Exception:
            pass
    return projects


# --------------------------------------------------------------------------- #
#  Heartbeat management API                                                   #
# --------------------------------------------------------------------------- #

def update_heartbeat(project_name: str, minutes: int) -> dict:
    """Update the heartbeat interval for a project."""
    proj = get_project(project_name)
    if proj is None:
        return {"error": f"Project '{project_name}' not found"}

    cron_id = proj.get("heartbeat_cron_id")
    if not cron_id:
        return {"error": f"Project '{project_name}' has no heartbeat cron job"}

    hermes = find_hermes_binary()
    schedule = f"every {minutes}m"
    try:
        result = subprocess.run(
            [hermes, "cron", "edit", cron_id, "--schedule", schedule],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return {"error": f"Failed to edit cron job: {result.stderr.strip()}"}
    except Exception as exc:
        return {"error": f"Failed to edit cron job: {exc}"}

    proj["heartbeat_minutes"] = minutes
    _project_file(project_name).write_text(json.dumps(proj, indent=2))
    logger.info("Project '%s' heartbeat updated to %dm", project_name, minutes)
    return {"status": "updated", "project": project_name, "heartbeat_minutes": minutes}


def pause_heartbeat(project_name: str) -> dict:
    """Pause a project's heartbeat cron job."""
    proj = get_project(project_name)
    if proj is None:
        return {"error": f"Project '{project_name}' not found"}

    hermes = find_hermes_binary()
    try:
        result = subprocess.run(
            [hermes, "cron", "pause", f"heartbeat-{safe_name(project_name)}"],
            capture_output=True, text=True, timeout=10,
        )
        return {"project": project_name, "paused": result.returncode == 0,
                "output": result.stdout.strip()}
    except Exception as exc:
        return {"error": str(exc)}


def resume_heartbeat(project_name: str) -> dict:
    """Resume a project's heartbeat cron job."""
    proj = get_project(project_name)
    if proj is None:
        return {"error": f"Project '{project_name}' not found"}

    hermes = find_hermes_binary()
    try:
        result = subprocess.run(
            [hermes, "cron", "resume", f"heartbeat-{safe_name(project_name)}"],
            capture_output=True, text=True, timeout=10,
        )
        return {"project": project_name, "resumed": result.returncode == 0,
                "output": result.stdout.strip()}
    except Exception as exc:
        return {"error": str(exc)}


def trigger_heartbeat(project_name: str) -> dict:
    """Manually trigger a project's heartbeat right now."""
    from agora.leader_loop import heartbeat
    return heartbeat(project=project_name)


def update_heartbeat_status(project_name: str, pid: int | None = None) -> None:
    """Update the last heartbeat timestamp for a project."""
    pf = _project_file(project_name)
    if not pf.exists():
        return
    data = json.loads(pf.read_text())
    data["last_heartbeat_at"] = now_iso()
    data["last_heartbeat_pid"] = pid
    pf.write_text(json.dumps(data, indent=2))


def get_heartbeat_member(project_name: str) -> str | None:
    """Get the heartbeat member (leader) for a project."""
    proj = get_project(project_name)
    if proj is None:
        return None
    return proj.get("heartbeat_member")


def get_leader_session(project_name: str) -> str | None:
    """Get the per-project leader session ID."""
    proj = get_project(project_name)
    if proj is None:
        return None
    return proj.get("leader_session_id")


def set_leader_session(project_name: str, session_id: str | None) -> None:
    """Set the per-project leader session ID."""
    pf = _project_file(project_name)
    if not pf.exists():
        return
    data = json.loads(pf.read_text())
    data["leader_session_id"] = session_id
    pf.write_text(json.dumps(data, indent=2))


def on_project_complete(project_name: str) -> None:
    """Handle project completion — stop heartbeat and update status."""
    try:
        # Pause cron job
        proj = get_project(project_name)
        if proj:
            cron_id = proj.get("heartbeat_cron_id")
            if cron_id:
                _remove_heartbeat_cron(cron_id)

            proj["status"] = "completed"
            proj["completed_at"] = now_iso()
            _project_file(project_name).write_text(json.dumps(proj, indent=2))

        logger.info("Project '%s' marked complete, heartbeat stopped", project_name)
    except Exception as exc:
        logger.error("Failed to handle project completion: %s", exc)


# --------------------------------------------------------------------------- #
#  Cron status helper (for dashboard)                                          #
# --------------------------------------------------------------------------- #

def get_cron_status(project_name: str) -> dict:
    """Get cron job status for a project's heartbeat."""
    import json as _json
    cron_jobs_path = Path.home() / ".hermes" / "profiles" / "coder" / "cron" / "jobs.json"
    cron_name = f"heartbeat-{safe_name(project_name)}"
    try:
        if cron_jobs_path.exists():
            cron_data = _json.loads(cron_jobs_path.read_text())
            for job in cron_data.get("jobs", []):
                if job.get("name") == cron_name:
                    return {
                        "enabled": job.get("enabled", False),
                        "next_run": job.get("next_run_at"),
                        "last_run": job.get("last_run_at"),
                        "schedule": job.get("schedule_display"),
                    }
    except Exception:
        pass
    return {"enabled": False}


# --------------------------------------------------------------------------- #
#  Hook entry point — called by kanban_task_completed                         #
# --------------------------------------------------------------------------- #

def on_task_completed(task_id: str, **kwargs: Any) -> None:
    """Called when a kanban task completes.

    Checks if the completed task belongs to an Agora-managed project.
    If so, and if there are no more pending tasks, logs that the leader
    will handle the next phase on its next heartbeat.
    """
    try:
        project_name = _find_project_for_task(task_id)
        if project_name is None:
            return

        data = get_project(project_name)
        if data is None or data.get("status") != "active":
            return

        if _has_pending_tasks():
            logger.info(
                "Project '%s': task %s done but pending tasks remain",
                project_name, task_id,
            )
            return

        logger.info(
            "Project '%s': all tasks done, leader will handle next phase on heartbeat",
            project_name,
        )
    except Exception as exc:
        logger.error("Planner hook error: %s", exc, exc_info=True)


# --------------------------------------------------------------------------- #
#  Helpers                                                                    #
# --------------------------------------------------------------------------- #

def _add_project_to_worker(worker_name: str, project_name: str) -> None:
    """Add a project to a worker's project list."""
    from agora.worker_manager import _worker_file
    wf = _worker_file(worker_name)
    if not wf.exists():
        return
    data = json.loads(wf.read_text())
    projects = data.get("projects", [])
    if project_name not in projects:
        projects.append(project_name)
        data["projects"] = projects
        wf.write_text(json.dumps(data, indent=2))


def _find_project_for_task(task_id: str) -> str | None:
    """Find the project name for a completed task."""
    try:
        from hermes_cli import kanban_db
        conn = kanban_db.connect()
        try:
            task = kanban_db.get_task(conn, task_id)
            if task and task.body:
                for proj in list_projects():
                    if proj["name"] in task.body:
                        return proj["name"]
                if "From Agora discussion" in task.body:
                    for proj in list_projects():
                        if proj.get("status") == "active":
                            return proj["name"]
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("Failed to find project for task %s: %s", task_id, exc)
    return None


def _has_pending_tasks() -> bool:
    """Check if there are any todo/ready/running tasks on the kanban board."""
    try:
        from hermes_cli import kanban_db
        conn = kanban_db.connect()
        try:
            rows = conn.execute(
                "SELECT COUNT(*) as n FROM tasks WHERE status IN ('todo', 'ready', 'running')"
            ).fetchone()
            return rows["n"] > 0
        finally:
            conn.close()
    except Exception:
        return False
