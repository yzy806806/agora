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

# Short responsibility descriptions for each role, shown in AGENTS.md
# so the leader knows what each team member does without reading their SOUL.md.
_ROLE_RESPONSIBILITIES = {
    "leader": "Project management, discussion chair, heartbeat, task dispatch",
    "architect": "System design, API contracts, technology selection, trade-off analysis",
    "developer": "Implementation, bug fixes, refactoring, dependency management",
    "reviewer": "Code review, security review, spec conformance, edge cases",
    "tester": "Test strategy, automated tests, bug verification, regression coverage",
    "devops": "CI/CD, containerization, deployment, monitoring, infrastructure",
    "researcher": "Web research, library evaluation, trend analysis, information synthesis",
    "writer": "Documentation, README, API docs, content production",
}

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
    """Write/update AGENTS.md in the project workdir.

    This file is auto-loaded by Hermes into every agent's system prompt
    (via TERMINAL_CWD context file scanning). It is the **single source
    of truth** for project context — goal, stop condition, team members,
    and active discussions. Both the leader (heartbeat) and workers
    (task dispatch, discussion) read this file automatically.

    Called on:
    - start_project (initial write)
    - leader heartbeat (refresh)
    - task claim (refresh)
    - project update (goal/stop_condition changed)
    - motion create/close
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

    # Gather team info with role template mapping
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

    if proj.get("description"):
        lines.append("## Description")
        lines.append("")
        lines.append(proj["description"])
        lines.append("")

    if proj.get("stop_condition"):
        lines.append("## Stop Condition")
        lines.append("")
        lines.append(f"The project should stop when: {proj['stop_condition']}")
        lines.append("If the stop condition appears to be met, the leader should raise a motion for the team to vote on whether to stop.")
        lines.append("")

    if proj.get("heartbeat_member"):
        lines.append(f"**Heartbeat Member:** {proj['heartbeat_member']} (woken every {proj.get('heartbeat_minutes', '?')} min)")
        lines.append("")

    # Team members table: profile name → role template (identity)
    # This lets the leader know who to dispatch for each task type,
    # and lets workers know who their teammates are.
    if members:
        lines.append("## Team Members")
        lines.append("")
        lines.append("| Profile Name | Role | Responsibilities |")
        lines.append("|---|---|---|")
        for m in members:
            is_hb = " (heartbeat)" if m["name"] == proj.get("heartbeat_member") else ""
            resp = _ROLE_RESPONSIBILITIES.get(m["role"], m["display_name"])
            lines.append(f"| {m['name']}{is_hb} | {m['role']} — {m['display_name']} | {resp} |")
        lines.append("")
        lines.append("Assign tasks by role name (e.g. `assignee='developer'`). The system routes to the correct worker automatically.")
        lines.append("")

    # Active discussions — gives everyone context on ongoing debates
    try:
        from agora.storage import motions as db
        active_motions = db.list_motions(status_filter="active", limit=10)
        if active_motions:
            lines.append("## Active Discussions")
            lines.append("")
            for m in active_motions:
                mid = m["id"][:22]
                title = m.get("title", "(untitled)")[:60]
                steps = m.get("step_count", 0) or 0
                max_steps = m.get("max_steps", 30) or 30
                state = m.get("state", "") or ""
                lines.append(f"- `[{mid}]` {title} (steps {steps}/{max_steps}, {state})")
            lines.append("")
    except Exception:
        pass

    # Kanban task summary — tells leader what's pending/done.
    # Query both the project board tenant AND tasks with no tenant
    # (NULL) — leader may have created tasks via kanban CLI which
    # doesn't set tenant. Without the NULL query, those tasks are
    # invisible in AGENTS.md and the leader thinks kanban is empty.
    try:
        from hermes_cli import kanban_db as _kdb
        board = proj.get("board") or f"agora-{safe_name(project_name)}"
        _conn = _kdb.connect()
        try:
            # Query by board tenant OR NULL tenant — both belong to this project.
            # list_tasks(tenant=board) only matches non-NULL tenants, so tasks
            # created via kanban CLI (which leaves tenant NULL) would be missed.
            def _list_project_tasks(conn, status):
                """List tasks for this project's board OR with NULL tenant."""
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE status = ? "
                    "AND (tenant = ? OR tenant IS NULL)",
                    (status, board),
                ).fetchall()
                return [_kdb.Task.from_row(r) for r in rows]

            _running = _list_project_tasks(_conn, "running")
            _ready = _list_project_tasks(_conn, "ready")
            _blocked = _list_project_tasks(_conn, "blocked")
            _review = _list_project_tasks(_conn, "review")
            _done = _list_project_tasks(_conn, "done")
        finally:
            _conn.close()
        lines.append("## Kanban Summary")
        lines.append("")
        lines.append(f"- Running: {len(_running)} | Ready: {len(_ready)} | Review: {len(_review)} | Blocked: {len(_blocked)} | Done: {len(_done)}")
        if _running:
            lines.append("")
            lines.append("**Running tasks:**")
            for t in _running[:5]:
                lines.append(f"- `{t.id}` assignee={t.assignee or '?'} — {t.title[:60]}")
            if len(_running) > 5:
                lines.append(f"- ... +{len(_running)-5} more")
        if _review:
            lines.append("")
            lines.append("**In review:**")
            for t in _review[:5]:
                lines.append(f"- `{t.id}` assignee={t.assignee or '?'} — {t.title[:60]}")
        if _ready:
            lines.append("")
            lines.append("**Ready (queued):**")
            for t in _ready[:5]:
                lines.append(f"- `{t.id}` assignee={t.assignee or '?'} — {t.title[:60]}")
            if len(_ready) > 5:
                lines.append(f"- ... +{len(_ready)-5} more")
        if _blocked:
            lines.append("")
            lines.append("**Blocked tasks:**")
            for t in _blocked[:5]:
                lines.append(f"- `{t.id}` assignee={t.assignee or '?'} — {t.title[:60]}")
            if len(_blocked) > 5:
                lines.append(f"- ... +{len(_blocked)-5} more")
        lines.append("")
    except Exception:
        pass

    # Last heartbeat info — tells leader when the last cycle ran
    last_hb = proj.get("last_heartbeat_at")
    if last_hb:
        lines.append(f"**Last heartbeat:** {last_hb}")
        lines.append("")

    # Recent motion results — tells leader what was recently decided.
    # Only show motions that actually had a discussion (step_count > 0) —
    # 0-step "adopted" motions were bypassed and should not appear as ✅.
    try:
        from agora.storage import motions as db
        recent = db.list_motions(status_filter="closed", limit=10)
        adopted = [
            m for m in recent
            if m.get("decision") == "adopted" and (m.get("step_count") or 0) > 0
        ]
        if adopted:
            lines.append("## Recent Decisions")
            lines.append("")
            for m in adopted[:3]:
                title = m.get("title", "")[:60]
                mid = m["id"][:22]
                lines.append(f"- `[{mid}]` ✅ {title}")
            lines.append("")
    except Exception:
        pass

    # Project-specific instructions
    lines.append("## Workflow")
    lines.append("")
    lines.append("1. Check your assigned tasks with `agora_project_status` or `hermes kanban list`.")
    lines.append("2. Use `kanban show <task_id>` to read task details.")
    lines.append("3. **Developer:** after completing a task, if your team has a `reviewer`,")
    lines.append("   use `agora_close_task(task_id, action='submit_review')` to submit for code")
    lines.append("   review. The reviewer will be auto-spawned. If no `reviewer` on team, use")
    lines.append("   `kanban complete <task_id>` as usual.")
    lines.append("4. **All other roles:** use `kanban complete <task_id>` when done.")
    lines.append("5. If blocked, use `kanban block <task_id>` with a clear explanation.")
    lines.append("6. For design decisions that need team input, use `agora_raise_motion`.")
    lines.append("7. **Never** use Python, terminal, or direct DB calls to manage tasks/motions.")
    lines.append("   Always use agora tools (`agora_raise_motion`, `agora_create_task`, etc.).")
    lines.append("")

    agents_path = workdir_path / "AGENTS.md"
    try:
        # Use atomic write (temp file + rename) to prevent partial reads
        # when multiple processes refresh AGENTS.md concurrently.
        import tempfile
        content = "\n".join(lines)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(workdir_path), prefix=".agents_md_", suffix=".tmp",
        )
        try:
            with os.fdopen(tmp_fd, "w") as tmp_f:
                tmp_f.write(content)
            os.replace(tmp_path, str(agents_path))
        except Exception:
            # Cleanup temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
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
        # Force GLOBAL hermes home so the cron job is registered in the
        # global ~/.hermes/cron/jobs.json — not the profile-scoped one.
        # When this function is called from a leader heartbeat subprocess
        # (hermes -p leader), HERMES_HOME is set to ~/.hermes/profiles/leader/,
        # which would cause the cron job to be invisible from the dashboard
        # and the gateway's main cron scheduler.
        cron_env = {**os.environ}
        cron_env["HERMES_HOME"] = str(Path.home() / ".hermes")
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=15,
            env=cron_env,
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
for d in "$HOME/.hermes/plugins/agora" "$(dirname "$(readlink -f "$0")")/.." /root/.hermes/plugins/agora; do
    [ -d "$d/agora" ] && PLUGIN="$d" && break
done

$PYTHON -c "
import sys, json, os, importlib.util
from pathlib import Path

_plugin_root = Path(os.environ.get('AGORA_PLUGIN_PATH', '$PLUGIN'))
_agora_pkg = _plugin_root / 'agora'

if 'agora' not in sys.modules and _agora_pkg.is_dir():
    _spec = importlib.util.spec_from_file_location('agora', _agora_pkg / '__init__.py', submodule_search_locations=[str(_agora_pkg)])
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules['agora'] = _mod
    _spec.loader.exec_module(_mod)

if 'project_planner' not in sys.modules:
    _pp = _plugin_root / 'project_planner.py'
    if _pp.exists():
        _spec = importlib.util.spec_from_file_location('project_planner', _pp)
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules['project_planner'] = _mod
        _spec.loader.exec_module(_mod)

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
        cron_env = {**os.environ}
        cron_env["HERMES_HOME"] = str(Path.home() / ".hermes")
        subprocess.run(
            [hermes, "cron", "remove", cron_id],
            capture_output=True, text=True, timeout=10,
            env=cron_env,
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
    description: str = "",
    stop_condition: str = "",
    initial_topic: str = "",
    max_rounds: int = 10,
    team: str | None = None,
    heartbeat_member: str | None = None,
    heartbeat_minutes: int = 15,
) -> dict:
    """Register a project for self-driving development.

    Args:
        project_name:      Short name (e.g. "docmind")
        workdir:           Absolute path to the project repo
        goal:              High-level goal (one-liner shown in project list)
        description:       Detailed project description (shown in AGENTS.md)
        stop_condition:    Natural-language stop condition (e.g. "All tests
                           pass and README is written"). Workers vote on
                           whether this is met before stopping.
        initial_topic:     First discussion topic (auto-generated if empty)
        max_rounds:        Maximum planning rounds before stopping
        team:              Team name for assignee routing
        heartbeat_member:  Worker name to wake on heartbeat (usually a leader)
        heartbeat_minutes: Heartbeat interval in minutes

    Returns:
        dict with status and project info
    """
    # Ensure workdir exists
    import os
    if workdir and not os.path.exists(workdir):
        os.makedirs(workdir, exist_ok=True)
        logger.info("Created project workdir: %s", workdir)

    pf = _project_file(project_name)
    board_name = _ensure_project_board(project_name)

    # Validate heartbeat_member if provided — runs for both new and
    # reactivated projects (M6 fix: previously only validated for new projects).
    if heartbeat_member:
        from agora.worker_manager import get_worker
        worker = get_worker(heartbeat_member)
        if worker is None:
            return {"error": f"Heartbeat member '{heartbeat_member}' not found in worker registry"}

    # If project already exists, preserve existing fields and just reactivate
    if pf.exists():
        existing = json.loads(pf.read_text())
        if existing.get("status") in ("active", "completed", "stopped"):
            logger.info(
                "Project %s already exists (status=%s) — reactivating, preserving fields",
                project_name, existing.get("status"),
            )
            # Update only status and heartbeat-related fields
            existing["status"] = "active"
            existing["current_round"] = existing.get("current_round", 0)
            existing["complete_count"] = 0
            existing["leader_session_id"] = None
            existing["completion_check_pos"] = 0
            # Preserve workdir if not provided
            if workdir:
                existing["workdir"] = workdir
            # Allow overriding heartbeat config if explicitly provided
            if heartbeat_member:
                existing["heartbeat_member"] = heartbeat_member
            if heartbeat_minutes != 15 or "heartbeat_minutes" not in existing:
                existing["heartbeat_minutes"] = heartbeat_minutes
            # Allow overriding goal/description/stop_condition if non-empty
            if goal:
                existing["goal"] = goal
            if description:
                existing["description"] = description
            if stop_condition:
                existing["stop_condition"] = stop_condition
            if team:
                existing["team"] = team
            # Recreate heartbeat cron if member is set and cron is missing or stale
            if existing.get("heartbeat_member"):
                old_cron_id = existing.get("heartbeat_cron_id")
                if old_cron_id:
                    # Verify the cron job still exists
                    import subprocess as _sp
                    _hermes = find_hermes_binary()
                    try:
                        _cron_env = {**os.environ}
                        _cron_env["HERMES_HOME"] = str(Path.home() / ".hermes")
                        _r = _sp.run(
                            [_hermes, "cron", "list", "--json"],
                            capture_output=True, text=True, timeout=15,
                            env=_cron_env,
                        )
                        _jobs = json.loads(_r.stdout) if _r.stdout.strip() else []
                        _active_ids = {j.get("id", "") for j in _jobs}
                        if old_cron_id not in _active_ids:
                            old_cron_id = None
                    except Exception:
                        old_cron_id = None
                if not old_cron_id:
                    cron_id = _create_heartbeat_cron(project_name, existing["heartbeat_minutes"])
                    if cron_id:
                        existing["heartbeat_cron_id"] = cron_id
            pf.write_text(json.dumps(existing, indent=2))
            update_project_agents_md(project_name)
            return existing

    # Warn if no team bound — leader won't be able to route tasks by role
    if not team:
        logger.warning(
            "Project '%s' started without a team — task assignee routing will "
            "fall back to 'default' profile. Call agora_update_project(name=%s, "
            "team=<team_name>) to bind a team.",
            project_name, project_name,
        )

    data = {
        "name": project_name,
        "workdir": workdir,
        "goal": goal,
        "description": description,
        "stop_condition": stop_condition,
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
        "complete_count": 0,
        "completion_check_pos": 0,
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
    """Stop a project and pause its heartbeat."""
    pf = _project_file(project_name)
    if not pf.exists():
        return {"error": f"Project '{project_name}' not found"}
    data = json.loads(pf.read_text())

    cron_id = data.get("heartbeat_cron_id")
    if cron_id:
        _remove_heartbeat_cron(cron_id)
    data["heartbeat_cron_id"] = None

    data["status"] = "stopped"
    pf.write_text(json.dumps(data, indent=2))
    logger.info("Project %s stopped", project_name)
    return {"status": "stopped", "project": data}


def update_project(
    project_name: str,
    goal: str | None = None,
    description: str | None = None,
    stop_condition: str | None = None,
    reactivate: bool = False,
) -> dict:
    """Update a project's goal, description, or stop condition mid-flight.

    This allows the leader to pivot a project's direction without stopping
    and recreating it. Automatically refreshes AGENTS.md so all workers
    see the new goal on their next spawn.

    Args:
        project_name:   Project to update
        goal:           New high-level goal (None = keep current)
        description:    New description (None = keep current)
        stop_condition: New stop condition (None = keep current)
        reactivate:     If True, set status back to "active" (e.g. after
                        the project was completed/stopped and needs a new
                        phase). Also re-creates the heartbeat cron if missing.

    Returns:
        dict with updated project info
    """
    pf = _project_file(project_name)
    if not pf.exists():
        return {"error": f"Project '{project_name}' not found"}
    data = json.loads(pf.read_text())

    changes = []
    if goal is not None:
        data["goal"] = goal
        changes.append("goal")
    if description is not None:
        data["description"] = description
        changes.append("description")
    if stop_condition is not None:
        data["stop_condition"] = stop_condition
        changes.append("stop_condition")

    if reactivate:
        data["status"] = "active"
        data["current_round"] = data.get("current_round", 0) + 1
        data["complete_count"] = 0
        data["leader_session_id"] = None
        data["completion_check_pos"] = 0
        # Re-create heartbeat cron if it was removed or is stale
        if data.get("heartbeat_member"):
            old_cron_id = data.get("heartbeat_cron_id")
            if old_cron_id:
                # Check if the cron job still exists
                import subprocess as _sp
                _hermes = find_hermes_binary()
                try:
                    _r = _sp.run(
                        [_hermes, "cron", "list", "--json"],
                        capture_output=True, text=True, timeout=15,
                    )
                    import json as _json
                    _jobs = _json.loads(_r.stdout) if _r.stdout.strip() else []
                    _active_ids = set()
                    for _j in _jobs:
                        _active_ids.add(_j.get("id", ""))
                    if old_cron_id not in _active_ids:
                        old_cron_id = None  # stale, treat as missing
                except Exception:
                    old_cron_id = None  # can't verify, recreate to be safe
            if not old_cron_id:
                cron_id = _create_heartbeat_cron(project_name, data.get("heartbeat_minutes", 15))
                if cron_id:
                    data["heartbeat_cron_id"] = cron_id
        changes.append("status=active")

    pf.write_text(json.dumps(data, indent=2))
    logger.info(
        "Project %s updated: %s",
        project_name, ", ".join(changes) if changes else "(no changes)",
    )

    # Refresh AGENTS.md so workers see the new goal immediately
    if changes:
        try:
            update_project_agents_md(project_name)
        except Exception as exc:
            logger.warning("Failed to refresh AGENTS.md: %s", exc)

    return {"status": "updated", "project": data, "changes": changes}


def delete_project(project_name: str) -> dict:
    """Permanently delete a project — stop heartbeat, remove registry file,
    and remove the project from all workers' projects lists."""
    pf = _project_file(project_name)
    if not pf.exists():
        return {"error": f"Project '{project_name}' not found"}
    data = json.loads(pf.read_text())

    # Pause cron job
    cron_id = data.get("heartbeat_cron_id")
    if cron_id:
        _remove_heartbeat_cron(cron_id)

    # Remove project from all workers' projects lists
    team = data.get("team")
    if team:
        try:
            from agora.team_manager import get_team
            tm = get_team(team)
            if tm:
                for w in tm.get("workers", []):
                    _remove_project_from_worker(w["name"], project_name)
        except Exception as exc:
            logger.warning("Worker cleanup failed for project '%s' (team=%s): %s", project_name, team, exc)
    heartbeat_member = data.get("heartbeat_member")
    if heartbeat_member and not team:
        _remove_project_from_worker(heartbeat_member, project_name)

    # Delete the project registry file
    pf.unlink()
    logger.info("Project %s deleted", project_name)
    return {"status": "deleted", "project": project_name}


def _remove_project_from_worker(worker_name: str, project_name: str) -> None:
    """Remove a project from a worker's projects list."""
    from agora.worker_manager import _worker_file
    wf = _worker_file(worker_name)
    if not wf.exists():
        return
    try:
        data = json.loads(wf.read_text())
        if project_name in data.get("projects", []):
            data["projects"].remove(project_name)
            wf.write_text(json.dumps(data, indent=2))
    except Exception as exc:
        logger.warning("Failed to remove project '%s' from worker '%s': %s", project_name, worker_name, exc)


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
    """Handle project completion — stop heartbeat, update status, archive tasks."""
    try:
        # Pause cron job
        proj = get_project(project_name)
        if proj:
            cron_id = proj.get("heartbeat_cron_id")
            if cron_id:
                _remove_heartbeat_cron(cron_id)
                proj["heartbeat_cron_id"] = None

            proj["status"] = "completed"
            proj["completed_at"] = now_iso()
            _project_file(project_name).write_text(json.dumps(proj, indent=2))

        # Delete all tasks belonging to this project so that when the
        # project is reactivated with a new goal, the kanban starts clean.
        # Without this, the leader sees hundreds of old done/archived tasks
        # and doesn't realize the project was restarted — it tries
        # PROJECT_COMPLETE immediately because "all tasks are done".
        try:
            from hermes_cli import kanban_db as _kdb
            board = f"agora-{safe_name(project_name)}"
            conn = _kdb.connect()
            try:
                # Get all task IDs for this project
                rows = conn.execute(
                    "SELECT id FROM tasks "
                    "WHERE (tenant = ? OR tenant IS NULL)",
                    (board,),
                ).fetchall()
                task_ids = [r[0] for r in rows]
                deleted = 0
                for tid in task_ids:
                    _kdb.delete_archived_task(conn, tid)
                    deleted += 1
                conn.commit()
                logger.info(
                    "Project '%s' complete: deleted %d kanban tasks",
                    project_name, deleted,
                )
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(
                "Failed to delete tasks on project completion: %s", exc
            )

        logger.info("Project '%s' marked complete, heartbeat stopped", project_name)
    except Exception as exc:
        logger.error("Failed to handle project completion: %s", exc)


# --------------------------------------------------------------------------- #
#  Cron status helper (for dashboard)                                          #
# --------------------------------------------------------------------------- #

def get_cron_status(project_name: str) -> dict:
    """Get cron job status for a project's heartbeat."""
    cron_name = f"heartbeat-{safe_name(project_name)}"
    # Check both the default profile and named profiles
    cron_paths = [
        Path.home() / ".hermes" / "cron" / "jobs.json",
    ]
    for cron_jobs_path in cron_paths:
        try:
            if cron_jobs_path.exists():
                cron_data = json.loads(cron_jobs_path.read_text())
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

        if _has_pending_tasks(project_name):
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
            if task:
                # Use the tenant field (kanban board name) for reliable
                # project association instead of string-matching task body.
                tenant = getattr(task, "tenant", None) or task.__dict__.get("tenant")
                if tenant:
                    # tenant is "agora-<project_name>" — strip the prefix
                    project_name = tenant.removeprefix("agora-")
                    # Verify this project exists in the registry
                    for proj in list_projects():
                        if proj["name"] == project_name:
                            return project_name
                    # Fallback: if no registry match, return the stripped name
                    # (the project may have been deleted but tasks remain)
                    if project_name:
                        return project_name
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("Failed to find project for task %s: %s", task_id, exc)
    return None


def _has_pending_tasks(project_name: str | None = None) -> bool:
    """Check if there are any todo/ready/running tasks on the kanban board.

    Args:
        project_name: If given, only count tasks for this project's board
                      (tenant = "agora-<project_name>"). If None, counts all.
    """
    try:
        from hermes_cli import kanban_db
        conn = kanban_db.connect()
        try:
            if project_name:
                tenant = f"agora-{project_name}"
                rows = conn.execute(
                    "SELECT COUNT(*) as n FROM tasks WHERE status IN ('todo', 'ready', 'running', 'blocked') AND tenant = ?",
                    (tenant,),
                ).fetchone()
            else:
                rows = conn.execute(
                    "SELECT COUNT(*) as n FROM tasks WHERE status IN ('todo', 'ready', 'running', 'blocked')"
                ).fetchone()
            return rows["n"] > 0
        finally:
            conn.close()
    except Exception:
        return False
