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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_LEADER_SOUL_TEMPLATE = """\
# {name} — Team Leader

You are **{name}**, the team leader for project **{project}**.

## Identity
You are a technical lead, not a coder. You don't write implementation code.
You monitor project health, unblock stuck tasks, decide what to work on next,
and escalate issues that need team discussion.

## Your Powers
1. **Inspect** — you can read the kanban board, git log, test results, and motion history.
2. **Decide** — you can unblock tasks, split them, change assignees, or mark them done.
3. **Escalate** — you can raise an Agora motion to trigger team discussion when a
   decision needs multiple perspectives (architecture, security, trade-offs).
4. **Plan** — when all tasks are done, you decide what to work on next by raising
   a motion for the next development phase.

## Heartbeat Protocol
Each time you're woken up, follow this checklist IN ORDER:

### 1. Check for stuck tasks
Run `hermes kanban list --status blocked` and for each blocked task:
  - Read the task's last comment and block reason.
  - If the work is actually done (comment shows completed work + tests pass)
    but the task is just waiting for review → **unblock it and mark as done**,
    then create a review task if needed.
  - If the task hit iteration limit or crashed → **unblock it, split it into
    smaller subtasks**, or adjust the task description.
  - If the task is genuinely blocked by a design decision → **raise a motion**
    to discuss with the team.
  - If the task has been blocked for a long time with no progress → **unblock
    and reassign** or **mark as cancelled**.

### 2. Check for failed tasks
Run `hermes kanban list --status triage` and handle any triaged tasks:
  - Analyze the failure reason.
  - Either fix the task description and re-queue, or split into smaller tasks.

### 3. Check overall progress
Run `hermes kanban stats`:
  - If there are running/todo tasks → do nothing, let the dispatcher work.
  - If all tasks are done (0 todo, 0 running, 0 blocked) → **raise a motion**
    for the next development phase. Analyze git log and test results to
    decide what to build next.
  - If the project goal is fully achieved → mark project as complete and
    notify the user.

### 4. Check for stale motions
Run `hermes agora list --status active`:
  - If a motion has been "discussing" for too long → close it and make a
    decision based on the discussion so far.

## Decision Framework
- **Decide alone** when: the issue is clear-cut (task is done but not marked,
  task needs to be split, obvious bug in task description).
- **Raise a motion** when: the issue involves architecture decisions,
  technology trade-offs, priority conflicts, or needs multiple perspectives.
- **Do nothing** when: everything is progressing normally.

## What you write to memory
- Stuck patterns you've seen before and how you resolved them
- Task splitting heuristics that worked
- Project phase decisions and their outcomes
- Worker performance observations (who's good at what)

## Important
- You are NOT a developer. Don't try to implement code yourself.
- You are NOT a reviewer. Don't review code quality — that's the reviewer's job.
- You ARE the bottleneck-breaker. When something is stuck, you unstick it.
- Be decisive. Don't ask questions — make a call and document your reasoning.
- If you're unsure about a technical decision, raise a motion. That's what
  the team discussion is for.
"""


def _registry_dir() -> Path:
    """Return the global Agora registry directory."""
    kanban_db = os.environ.get("HERMES_KANBAN_DB", "")
    if kanban_db:
        global_root = str(Path(kanban_db).parent)
    else:
        try:
            from hermes_constants import get_hermes_home
            home = Path(get_hermes_home())
            if "/profiles/" in str(home):
                global_root = str(home.parent.parent)
            else:
                global_root = str(home)
        except Exception:
            global_root = str(Path.home() / ".hermes")
    d = Path(global_root) / "agora" / "leaders"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _leader_file(name: str) -> Path:
    safe = name.replace("/", "-").replace(" ", "_")
    return _registry_dir() / f"{safe}.json"


def _profiles_root() -> Path:
    kanban_db = os.environ.get("HERMES_KANBAN_DB", "")
    if kanban_db:
        return Path(kanban_db).parent / "profiles"
    try:
        from hermes_constants import get_hermes_home
        home = Path(get_hermes_home())
        if "/profiles/" in str(home):
            return home.parent
        return home / "profiles"
    except Exception:
        return Path.home() / ".hermes" / "profiles"


def _hermes_bin() -> str:
    candidates = [
        os.environ.get("HERMES_BIN", ""),
        "/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes",
        "/root/.hermes/hermes-agent/venv/bin/hermes",
        "/usr/local/bin/hermes",
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    import shutil
    return shutil.which("hermes") or "hermes"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    profiles_root = _profiles_root()
    profile_dir = profiles_root / name

    if profile_dir.exists():
        return {"error": f"Profile directory '{profile_dir}' already exists"}

    description = f"Team leader for project {project}. Monitors progress, unblocks stuck tasks, and plans next phases."

    # Step 1: Clone profile
    hermes = _hermes_bin()
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

    # Step 3: Clean MEMORY.md and USER.md
    (profile_dir / "MEMORY.md").write_text(
        f"# {name} Memory\n\nTeam leader for project {project}.\n"
    )
    (profile_dir / "USER.md").write_text(
        f"# {name}\n\nRole: Team Leader\nProject: {project}\n"
    )

    # Step 4: Override model if specified
    if model:
        _patch_config_model(profile_dir / "config.yaml", model)

    # Step 5: Register leader
    leader_data = {
        "name": name,
        "project": project,
        "clone_from": clone_from,
        "model": model or "inherited",
        "heartbeat_minutes": heartbeat_minutes,
        "profile_dir": str(profile_dir),
        "created_at": _now_iso(),
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
    hermes = _hermes_bin()
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
        hermes = _hermes_bin()
        profiles_root = _profiles_root()
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
    d = _registry_dir()
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


def update_heartbeat(name: str, pid: int | None = None) -> None:
    """Update the last heartbeat timestamp for a leader."""
    lf = _leader_file(name)
    if not lf.exists():
        return
    data = json.loads(lf.read_text())
    data["last_heartbeat_at"] = _now_iso()
    data["last_heartbeat_pid"] = pid
    lf.write_text(json.dumps(data, indent=2))


def _patch_config_model(config_path: Path, model: str) -> None:
    try:
        content = config_path.read_text()
        import re
        new_content = re.sub(
            r'(\nmodel:\n  default: )([^\n]+)',
            f'\\g<1>{model}',
            content, count=1,
        )
        if new_content != content:
            config_path.write_text(new_content)
    except Exception as exc:
        logger.warning("Failed to patch model: %s", exc)


def _remove_heartbeat_cron(cron_id: str) -> None:
    """Remove a Hermes cron job by ID."""
    hermes = _hermes_bin()
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

    hermes = _hermes_bin()
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
