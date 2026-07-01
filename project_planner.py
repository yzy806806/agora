"""Self-driving project loop — project lifecycle management.

In the new architecture, the Leader IS the planner. When all tasks are
done, the Leader's heartbeat prompt tells it to:
  1. Check if the project goal is achieved -> output PROJECT_COMPLETE
  2. If not -> plan the next phase and create tasks directly

This module handles:
  - start_project: register project, kick off initial tasks
  - stop_project: stop a project manually
  - get/list projects for dashboard display
  - on_task_completed: hook entry point (checks if project is complete)

The old _spawn_planner function is kept for backward compatibility but
is no longer the primary driver — the Leader heartbeat is.
"""
from __future__ import annotations

import json
import logging

from agora.utils import get_registry_dir, safe_name, find_hermes_binary, now_iso
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project registry — tracks which projects are in self-drive mode
# ---------------------------------------------------------------------------



def _project_file(project_name: str) -> Path:
    return get_registry_dir("projects") / f"{safe_name(project_name)}.json"


def start_project(
    project_name: str,
    workdir: str,
    goal: str = "",
    initial_topic: str = "",
    profile: str = "coder",
    max_rounds: int = 10,
    team: str | None = None,
) -> dict:
    """Register a project for self-driving development.

    Args:
        project_name: Short name (e.g. "docmind")
        workdir: Absolute path to the project repo
        goal: High-level goal (e.g. "Build a document intelligence platform")
        initial_topic: First discussion topic. If empty, auto-generated.
        profile: Hermes profile to use for workers and planner
        max_rounds: Maximum planning rounds before stopping

    Returns:
        dict with status and project info
    """
    pf = _project_file(project_name)
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
        "last_planner_pid": None,
        "last_planner_at": None,
        "team": team,  # optional team name for assignee routing
    }
    pf.write_text(json.dumps(data, indent=2))
    logger.info("Project %s started: %s", project_name, workdir)

    # Leader heartbeat will handle planning automatically
    return {"status": "started", "project": data}


def stop_project(project_name: str) -> dict:
    """Stop a self-driving project."""
    pf = _project_file(project_name)
    if not pf.exists():
        return {"error": f"Project '{project_name}' not found"}
    data = json.loads(pf.read_text())
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


# ---------------------------------------------------------------------------#
# Hook entry point — called by kanban_task_completed
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_project_for_task(task_id: str) -> str | None:
    """Find the project name for a completed task.

    Strategy:
    1. Check all active projects — see if the task body contains
       "From Agora discussion" and match the motion to a project.
    2. If no match, check if the task was created by a planner (via
       the task body's project name field).
    """
    try:
        from hermes_cli import kanban_db
        conn = kanban_db.connect()
        try:
            task = kanban_db.get_task(conn, task_id)
            if task and task.body:
                # Look for project name in task body
                # The planner prompt includes the project name
                for proj in list_projects():
                    if proj["name"] in task.body:
                        return proj["name"]
                # Check for "From Agora discussion" marker
                if "From Agora discussion" in task.body:
                    # Task was created by Agora — find which project
                    # by matching workdir
                    for proj in list_projects():
                        if proj.get("status") == "active":
                            return proj["name"]
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("Failed to find project for task %s: %s", task_id, exc)
    return None


def _has_pending_tasks() -> bool:
    """Check if there are any todo/ready/running tasks on the kanban board.

    Running tasks are included because a worker may still be executing —
    we only want to spawn a planner when the board is truly empty of
    in-flight or queued work.
    """
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
