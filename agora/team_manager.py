"""Team manager — compose worker pools for projects.

A "team" is a set of worker profiles assigned to a project. The same
worker can be on multiple teams (multiple projects), just like a real
employee working on multiple projects simultaneously.

Teams serve as the assignee pool for kanban task dispatch: when a
discussion produces action items with owner=architect, the dispatcher
picks a worker from the team whose role=architect.

Example:
    Workers: alice(architect), bob(developer), carol(reviewer)
    Team "docmind":  [alice, bob, carol]
    Team "webapp":   [alice, bob, dave(developer)]

    docmind tasks with owner=architect → assigned to alice
    webapp tasks with owner=architect  → assigned to alice (same person)
    webapp tasks with owner=developer  → assigned to bob OR dave (round-robin)
"""
from __future__ import annotations

import json
import logging

from .utils import get_registry_dir, safe_name, now_iso
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)




def _team_file(team_name: str) -> Path:
    return get_registry_dir("teams") / f"{safe_name(team_name)}.json"


# --------------------------------------------------------------------------- #
#  Public API                                                                 #
# --------------------------------------------------------------------------- #

def create_team(
    team_name: str,
    worker_names: list[str],
    project: str | None = None,
) -> dict:
    """Create a team by selecting existing workers.

    Args:
        team_name:    Unique team name (e.g. "docmind-team")
        worker_names: List of worker profile names to include
        project:      Optional project to bind this team to

    Returns:
        dict with team info
    """
    from .worker_manager import get_worker, _worker_file as _wf

    if not team_name or not worker_names:
        return {"error": "team_name and worker_names are required"}

    if _team_file(team_name).exists():
        return {"error": f"Team '{team_name}' already exists. Remove it first."}

    # Validate all workers exist
    from .worker_manager import list_workers
    existing = {w["name"] for w in list_workers()}
    missing = [w for w in worker_names if w not in existing]
    if missing:
        return {
            "error": f"Workers not found: {missing}. Create them first with agora_create_worker.",
        }

    # Build team roster with role mapping
    roster = []
    role_map: dict[str, list[str]] = {}  # role → [worker names]
    for wname in worker_names:
        wdata = get_worker(wname)
        if wdata is None:
            continue
        entry = {
            "name": wname,
            "role": wdata["role"],
            "display_name": wdata.get("display_name", wdata["role"]),
        }
        roster.append(entry)
        role_map.setdefault(wdata["role"], []).append(wname)

    team_data = {
        "name": team_name,
        "workers": roster,
        "role_map": role_map,  # role → [worker names] for dispatch routing
        "project": project,
        "created_at": now_iso(),
        "dispatch_counters": {},  # role → int, for round-robin
    }

    _team_file(team_name).write_text(json.dumps(team_data, indent=2))

    # If project is specified, bind team to project
    if project:
        _bind_team_to_project(team_name, project)
        # Update each worker's project list
        for wname in worker_names:
            _add_project_to_worker(wname, project)

    logger.info(
        "Team '%s' created with %d workers: %s (project=%s)",
        team_name, len(roster),
        ", ".join(f"{w['name']}({w['role']})" for w in roster),
        project,
    )

    return {"status": "created", "team": team_data}


def remove_team(team_name: str) -> dict:
    """Remove a team from the registry."""
    tf = _team_file(team_name)
    if not tf.exists():
        return {"error": f"Team '{team_name}' not found"}

    data = json.loads(tf.read_text())

    # Unbind from project
    project = data.get("project")
    if project:
        _unbind_team_from_project(team_name, project)
        # Remove project from each worker's project list
        for w in data.get("workers", []):
            _remove_project_from_worker(w["name"], project)

    tf.unlink()
    logger.info("Team '%s' removed", team_name)
    return {"status": "removed", "team": team_name}


def get_team(team_name: str) -> dict | None:
    """Get team data."""
    tf = _team_file(team_name)
    if not tf.exists():
        return None
    return json.loads(tf.read_text())


def list_teams() -> list[dict]:
    """List all registered teams."""
    d = get_registry_dir("teams")
    teams = []
    for f in d.glob("*.json"):
        try:
            teams.append(json.loads(f.read_text()))
        except Exception:
            pass
    return teams


def get_team_for_project(project_name: str) -> dict | None:
    """Find the team bound to a project."""
    for team in list_teams():
        if team.get("project") == project_name:
            return team
    return None


def get_assignee_for_role(team_name: str, role: str) -> str | None:
    """Pick a worker from the team for a given role (round-robin).

    This is the core dispatch routing function. When a discussion produces
    an action item with owner=architect, this function returns the next
    architect worker in the team's rotation.

    Returns None if no worker with that role is on the team.
    """
    team = get_team(team_name)
    if team is None:
        return None

    role_map = team.get("role_map", {})
    workers = role_map.get(role, [])
    if not workers:
        # Try to find a worker with a matching role by checking the roster
        # (handles case where role_map wasn't built correctly)
        for w in team.get("workers", []):
            if w.get("role") == role:
                workers.append(w["name"])
        if not workers:
            return None

    # Round-robin using dispatch_counters
    counters = team.get("dispatch_counters", {})
    idx = counters.get(role, 0)
    picked = workers[idx % len(workers)]

    # Update counter
    counters[role] = (idx + 1) % len(workers)
    team["dispatch_counters"] = counters
    _team_file(team_name).write_text(json.dumps(team, indent=2))

    return picked


# --------------------------------------------------------------------------- #
#  Internal helpers                                                           #
# --------------------------------------------------------------------------- #

def _bind_team_to_project(team_name: str, project_name: str) -> None:
    """Write the team name into the project registry file."""
    try:
        from ..project_planner import _project_file, get_project
        data = get_project(project_name)
        if data is None:
            logger.warning("Cannot bind team to project: project '%s' not found", project_name)
            return
        data["team"] = team_name
        _project_file(project_name).write_text(json.dumps(data, indent=2))
    except Exception as exc:
        logger.warning("Failed to bind team '%s' to project '%s': %s", team_name, project_name, exc)


def _unbind_team_from_project(team_name: str, project_name: str) -> None:
    """Remove the team binding from the project registry file."""
    try:
        from ..project_planner import _project_file, get_project
        data = get_project(project_name)
        if data is None:
            return
        data.pop("team", None)
        _project_file(project_name).write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def _add_project_to_worker(worker_name: str, project_name: str) -> None:
    """Add a project to a worker's project list."""
    from .worker_manager import _worker_file
    wf = _worker_file(worker_name)
    if not wf.exists():
        return
    data = json.loads(wf.read_text())
    projects = data.get("projects", [])
    if project_name not in projects:
        projects.append(project_name)
        data["projects"] = projects
        wf.write_text(json.dumps(data, indent=2))


def _remove_project_from_worker(worker_name: str, project_name: str) -> None:
    """Remove a project from a worker's project list."""
    from .worker_manager import _worker_file
    wf = _worker_file(worker_name)
    if not wf.exists():
        return
    data = json.loads(wf.read_text())
    projects = data.get("projects", [])
    if project_name in projects:
        projects.remove(project_name)
        data["projects"] = projects
        wf.write_text(json.dumps(data, indent=2))


