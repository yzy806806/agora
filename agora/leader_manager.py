"""Leader manager — create and manage team leader profiles.

A Leader is a special worker profile that:
  - Does NOT accept kanban tasks (not a developer/architect/reviewer)
  - Gets woken up periodically by a heartbeat (cron job)
  - Checks global project health and makes decisions:
    - Stuck tasks → unblock, split, retry, or reassign
    - All tasks done → raise a motion for next phase
    - Everything fine → do nothing
  - Can raise motions to trigger team discussion when needed
  - Has its own memory, skills, and SOUL.md identity

The Leader is the ONLY external trigger point. All other workers
are dispatched by the kanban dispatcher, which is controlled by
the Leader's decisions (raising motions → action items → tasks).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from .utils import (
    get_registry_dir,
    get_profiles_root,
    find_hermes_binary,
    now_iso,
    patch_config_model,
    safe_name,
    ensure_in_place_compression,
)

logger = logging.getLogger(__name__)


from .worker_templates import TEMPLATES as _TEMPLATES, render_soul as _render_soul

_LEADER_SOUL_TEMPLATE = _TEMPLATES["leader"]["soul_template"]


def _leader_file(name: str) -> Path:
    return get_registry_dir("leaders") / f"{safe_name(name)}.json"


# --------------------------------------------------------------------------- #
#  Public API                                                                 #
# --------------------------------------------------------------------------- #

def create_leader(
    name: str,
    project: str,
    clone_from: str = "coder",
    heartbeat_minutes: int = 15,
    model: str | None = None,
) -> dict:
    """Create a leader profile for a project.

    Args:
        name:               Profile name (e.g. "frank")
        project:            Project name this leader manages
        clone_from:         Source profile to clone config from
        heartbeat_minutes:  How often to wake the leader (default 15 min)
        model:              Override model (optional)

    Returns:
        dict with creation status
    """
    if not name or not project:
        return {"error": "name and project are required"}

    if _leader_file(name).exists():
        return {"error": f"Leader '{name}' already exists"}

    profiles_root = get_profiles_root()
    profile_dir = profiles_root / name

    if profile_dir.exists():
        return {"error": f"Profile directory '{profile_dir}' already exists"}

    description = f"Team leader for project {project}. Monitors progress, unblocks stuck tasks, and plans next phases."

    # Step 1: Clone profile
    hermes = find_hermes_binary()
    clone_cmd = [
        hermes, "profile", "create", name,
        "--clone-from", clone_from,
        "--description", description,
    ]
    try:
        result = subprocess.run(
            clone_cmd,
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "HERMES_HOME": str(profiles_root.parent)},
        )
        if result.returncode != 0:
            return {"error": f"Failed to clone profile: {result.stderr.strip()}"}
    except Exception as exc:
        return {"error": f"Failed to clone profile: {exc}"}

    # Step 2: Write SOUL.md
    soul_path = profile_dir / "SOUL.md"
    soul_path.write_text(_LEADER_SOUL_TEMPLATE.format(name=name, project=project))

    # Step 3: Clean memories/MEMORY.md and memories/USER.md
    # NOTE: Hermes v0.18 memory tool uses <profile>/memories/ directory
    memories_dir = profile_dir / "memories"
    memories_dir.mkdir(parents=True, exist_ok=True)
    (memories_dir / "MEMORY.md").write_text(
        f"# {name} Memory\n\nTeam leader for project {project}.\n"
    )
    (memories_dir / "USER.md").write_text(
        f"# {name}\n\nRole: Team Leader\nProject: {project}\n"
    )

    # Step 4: Override model if specified
    if model:
        patch_config_model(profile_dir / "config.yaml", model)

    # Step 4b: Ensure compression.in_place: true so session IDs don't change
    # on context compression — the leader's --resume always works.
    ensure_in_place_compression(profile_dir / "config.yaml")

    # Step 5: Register leader
    leader_data = {
        "name": name,
        "project": project,
        "clone_from": clone_from,
        "model": model or "inherited",
        "heartbeat_minutes": heartbeat_minutes,
        "profile_dir": str(profile_dir),
        "created_at": now_iso(),
        "last_heartbeat_at": None,
        "last_heartbeat_pid": None,
        "status": "active",
        "cron_job_id": None,  # set by _setup_cron_job
    }
    _leader_file(name).write_text(json.dumps(leader_data, indent=2))

    # Step 6: Create Hermes cron job for heartbeat
    cron_id = _create_heartbeat_cron(name, heartbeat_minutes)
    if cron_id:
        leader_data["cron_job_id"] = cron_id
        _leader_file(name).write_text(json.dumps(leader_data, indent=2))

    logger.info("Leader '%s' created for project '%s' (heartbeat=%dm, cron=%s)",
                name, project, heartbeat_minutes, cron_id)

    return {"status": "created", "leader": leader_data}


def _create_heartbeat_cron(leader_name: str, minutes: int) -> str | None:
    """Create a Hermes cron job that triggers heartbeat for a leader.

    Uses --no-agent + --script mode: the script calls heartbeat(leader_name),
    which spawns the leader agent. The cron job runs inside the gateway
    process, so it works even when no external system is pinging.

    Returns the cron job ID, or None on failure.
    """
    hermes = find_hermes_binary()
    schedule = f"every {minutes}m"
    job_name = f"heartbeat-{leader_name}"
    script_name = "leader_heartbeat.sh"

    # Ensure the script exists and supports per-leader invocation
    _ensure_heartbeat_script()

    cmd = [
        hermes, "cron", "create", schedule,
        "--name", job_name,
        "--no-agent",
        "--script", script_name,
        "--deliver", "local",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=15,
            env={**os.environ},
        )
        if result.returncode == 0:
            # Extract job ID from output: "Created job: <id>"
            for line in result.stdout.split("\n"):
                if "Created job:" in line:
                    job_id = line.split("Created job:")[1].strip().split()[0]
                    logger.info("Cron job %s created for leader %s", job_id, leader_name)
                    return job_id
        logger.warning("Failed to create cron job: %s", result.stderr or result.stdout)
    except Exception as exc:
        logger.warning("Failed to create cron job: %s", exc)
    return None


def _ensure_heartbeat_script() -> None:
    """Ensure the leader_heartbeat.sh script exists in ~/.hermes/scripts/.

    The script wakes all active leaders. Individual leader cron jobs
    all use the same script — the script itself decides who to wake
    based on the leader registry.
    """
    try:
        kanban_db = os.environ.get("HERMES_KANBAN_DB", "")
        if kanban_db:
            scripts_dir = Path(kanban_db).parent / "scripts"
        else:
            scripts_dir = Path.home() / ".hermes" / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        script_path = scripts_dir / "leader_heartbeat.sh"
        if script_path.exists():
            return  # already created

        script_content = """#!/bin/bash
# Leader heartbeat — called by Hermes cron scheduler.
# Wakes ALL active leaders. Each leader follows its SOUL.md protocol.
# To change a specific leader's interval: hermes cron edit <job_id> --schedule "30m"
# To pause: hermes cron pause <job_name>
# To resume: hermes cron resume <job_name>

export HERMES_KANBAN_DB="${HERMES_KANBAN_DB:-/root/.hermes/kanban.db}"

PYTHON=""
for p in /home/ubuntu/.hermes/hermes-agent/venv/bin/python3 /root/.hermes/hermes-agent/venv/bin/python3 /usr/bin/python3; do
    [ -x "$p" ] && PYTHON="$p" && break
done
[ -z "$PYTHON" ] && PYTHON=python3

PLUGIN=""
for d in /root/.hermes/profiles/coder/plugins/agora /root/.hermes/plugins/agora; do
    [ -d "$d" ] && PLUGIN="$d" && break
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


def remove_leader(name: str, delete_profile: bool = True) -> dict:
    """Remove a leader from the registry."""
    lf = _leader_file(name)
    if not lf.exists():
        return {"error": f"Leader '{name}' not found"}

    data = json.loads(lf.read_text())

    # Remove cron job if exists
    cron_id = data.get("cron_job_id")
    if cron_id:
        _remove_heartbeat_cron(cron_id)

    if delete_profile:
        hermes = find_hermes_binary()
        profiles_root = get_profiles_root()
        try:
            subprocess.run(
                [hermes, "profile", "delete", name, "--yes"],
                capture_output=True, text=True, timeout=15,
                env={**os.environ, "HERMES_HOME": str(profiles_root.parent)},
            )
        except Exception:
            import shutil
            profile_dir = profiles_root / name
            if profile_dir.exists():
                shutil.rmtree(profile_dir, ignore_errors=True)

    lf.unlink()
    return {"status": "removed", "leader": name}


def get_leader(name: str) -> dict | None:
    lf = _leader_file(name)
    if not lf.exists():
        return None
    return json.loads(lf.read_text())


def list_leaders() -> list[dict]:
    d = get_registry_dir("leaders")
    leaders = []
    for f in d.glob("*.json"):
        try:
            leaders.append(json.loads(f.read_text()))
        except Exception:
            pass
    return leaders


def get_leader_for_project(project: str) -> dict | None:
    for leader in list_leaders():
        if leader.get("project") == project and leader.get("status") == "active":
            return leader
    return None


def bind_leader_to_project(name: str, project: str) -> dict:
    """Bind (or rebind) a leader to a project in the registry.

    Reads the leader JSON, updates the ``project`` field, and writes it back.
    Returns a status dict.  This replaces the fragile inline read-modify-write
    pattern that callers (e.g. ``plugin_api.start_project_api``) used to do
    directly with ``_leader_file``.
    """
    leader = get_leader(name)
    if leader is None:
        return {"error": f"Leader '{name}' not found"}
    leader["project"] = project
    _leader_file(name).write_text(json.dumps(leader, indent=2))
    logger.info("Leader '%s' bound to project '%s'", name, project)
    return {"status": "bound", "leader": name, "project": project}


def update_heartbeat(name: str, pid: int | None = None) -> None:
    """Update the last heartbeat timestamp for a leader."""
    lf = _leader_file(name)
    if not lf.exists():
        return
    data = json.loads(lf.read_text())
    data["last_heartbeat_at"] = now_iso()
    data["last_heartbeat_pid"] = pid
    lf.write_text(json.dumps(data, indent=2))


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


def update_heartbeat_schedule(name: str, minutes: int) -> dict:
    """Update the heartbeat interval for a leader.

    This edits the Hermes cron job's schedule.
    """
    leader = get_leader(name)
    if leader is None:
        return {"error": f"Leader '{name}' not found"}

    cron_id = leader.get("cron_job_id")
    if not cron_id:
        return {"error": f"Leader '{name}' has no cron job. Create the leader first."}

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

    # Update leader registry
    leader["heartbeat_minutes"] = minutes
    _leader_file(name).write_text(json.dumps(leader, indent=2))

    logger.info("Leader '%s' heartbeat updated to %dm", name, minutes)
    return {"status": "updated", "leader": name, "heartbeat_minutes": minutes}
