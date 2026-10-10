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
import sys
import time
from pathlib import Path
from typing import Any

from .agora.utils import (
    get_registry_dir,
    get_global_root,
    safe_name,
    find_hermes_binary,
    now_iso,
    capture_hermes_import_env,
)

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


def _ensure_chat_channel(project_name: str, board_name: str, team: str | None, heartbeat_member: str | None) -> None:
    """Create the 2.0 team chat root and subscribe all known workers.

    The chat root is a persistent Kanban task pinned ``scheduled``; workers
    post ``[agora:msg]`` comments and pull unseen messages via notify cursors
    (see agora.chat). Persists ``chat_root_id`` into the project JSON.
    """
    try:
        from .agora.chat import ensure_chat_root, subscribe_worker
        from .agora.kanban_compat import kanban_db as _kdb
        conn = _kdb.connect()
        try:
            root_id = ensure_chat_root(
                conn, project_name=project_name, tenant=board_name, created_by="agora",
            )
            # Subscribe all team workers + the heartbeat member.
            workers: list[str] = []
            if team:
                from .agora.team_manager import get_team
                tm = get_team(team)
                if tm:
                    workers = [w["name"] for w in tm.get("workers", [])]
            if heartbeat_member and heartbeat_member not in workers:
                workers.append(heartbeat_member)
            for w in workers:
                try:
                    subscribe_worker(conn, root_id=root_id, worker=w)
                except Exception as sub_exc:
                    logger.warning("Failed to subscribe %s to chat: %s", w, sub_exc)

            # Persist the real task id.
            pf = _project_file(project_name)
            if pf.exists():
                data = json.loads(pf.read_text())
                data["chat_root_id"] = root_id
                pf.write_text(json.dumps(data, indent=2))
            logger.info("Chat channel ready for project %s (root=%s, workers=%d)", project_name, root_id, len(workers))
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Chat channel setup failed for %s: %s", project_name, exc)


def _ensure_project_board(project_name: str) -> str:
    """Create a kanban board name for the project.

    Returns the board name (used as kanban tenant for project isolation).
    """
    board_name = agora_board_for(project_name)
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
            from .agora.team_manager import get_team
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
        from .agora.storage import motions_kanban as db
        active_motions = db.list_motions(status_filter="active", limit=10, project=project_name)
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

    # Kanban task summary — tells the leader what's pending/done.
    # Scoped to this project's board (tenant). Agora sets the tenant on every
    # task it creates, so anything without one belongs to another producer.
    try:
        from .agora.kanban_compat import kanban_db as _kdb
        from .agora.utils import PENDING_TASK_STATUSES, STATUS_LABELS

        board = proj.get("board") or agora_board_for(project_name)
        _conn = _kdb.connect()
        try:
            # Scope strictly to this project's board: Agora always sets
            # `tenant` when it creates a task, so a NULL tenant means the task
            # belongs to someone else. Matching NULL here would pull in every
            # un-tenanted task in the database.
            def _list_project_tasks(conn, status):
                """List this project's board tasks in the given status."""
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE status = ? AND tenant = ?",
                    (status, board),
                ).fetchall()
                return [_kdb.Task.from_row(r) for r in rows]

            _buckets: dict = {}
            for _status in (*PENDING_TASK_STATUSES, "done"):
                _buckets[_status] = _list_project_tasks(_conn, _status)
        finally:
            _conn.close()
        lines.append("## Kanban Summary")
        lines.append("")
        # Every pending status must appear: the leader reads this to decide
        # whether the board is clean. Motions and any child of a non-done parent
        # sit in `todo`, so omitting it hides in-flight discussion from the
        # leader entirely.
        lines.append(
            "- "
            + " | ".join(
                f"{STATUS_LABELS[_s]}: {len(_buckets[_s])}"
                for _s in (*PENDING_TASK_STATUSES, "done")
            )
        )
        for _status in PENDING_TASK_STATUSES:
            _tasks = _buckets[_status]
            if not _tasks:
                continue
            lines.append("")
            lines.append(f"**{STATUS_LABELS[_status]} tasks:**")
            for t in _tasks[:5]:
                lines.append(f"- `{t.id}` assignee={t.assignee or '?'} — {t.title[:60]}")
            if len(_tasks) > 5:
                lines.append(f"- ... +{len(_tasks)-5} more")
        lines.append("")
    except Exception as exc:
        # Don't let a board read break the heartbeat — but don't drop the
        # leader's only view of pending work silently either. Without this
        # line a failed summary renders exactly like a clean board, which is
        # how an in-flight motion stayed invisible in the first place.
        logger.warning(
            "update_project_agents_md: kanban summary for '%s' failed: %s", project_name, exc,
        )

    # Last heartbeat info — tells leader when the last cycle ran
    last_hb = proj.get("last_heartbeat_at")
    if last_hb:
        lines.append(f"**Last heartbeat:** {last_hb}")
        lines.append("")

    # Recent motion results — tells leader what was recently decided.
    # Only show motions that actually had a discussion (step_count > 0) —
    # 0-step "adopted" motions were bypassed and should not appear as ✅.
    try:
        from .agora.storage import motions_kanban as db
        recent = db.list_motions(status_filter="closed", limit=10, project=project_name)
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
    lines.append("   use `kanban_request_review(task_id, summary=\"...\")` to submit for code")
    lines.append("   review (summary describes what was implemented + how it was verified).")
    lines.append("   The reviewer is auto-spawned. If the reviewer requests changes, fix the")
    lines.append("   findings and re-submit. If no `reviewer` on team, use `kanban complete`.")
    lines.append("4. **Reviewer:** approve with `kanban complete`; reject with")
    lines.append("   `kanban_request_changes(task_id, reason=\"concrete findings\")` — the")
    lines.append("   task routes back to the implementer automatically.")
    lines.append("5. **All other roles:** use `kanban complete <task_id>` when done.")
    lines.append("6. If blocked, use `kanban block <task_id>` with a clear explanation.")
    lines.append("7. For design decisions that need team input, use `agora_raise_motion`.")
    lines.append("8. **Never** use Python, terminal, or direct DB calls to manage tasks/motions.")
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
        cron_env["HERMES_HOME"] = str(get_global_root())
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
    """Write leader_heartbeat.sh into ``<hermes_home>/scripts/``.

    Rewritten whenever the content differs, so upgrades reach installs that
    already have an older script. Every path is resolved at runtime from
    ``HERMES_HOME`` / the script's own location — no install layout is
    hardcoded.
    """
    try:
        kanban_db = os.environ.get("HERMES_KANBAN_DB", "")
        scripts_dir = (Path(kanban_db).parent if kanban_db else get_global_root()) / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        script_path = scripts_dir / "leader_heartbeat.sh"

        script_content = """#!/bin/bash
# Leader heartbeat — called by Hermes cron scheduler.
# Wakes ALL active project leaders. Each leader follows its SOUL.md protocol.
# To change a specific project's interval: hermes cron edit <job_id> --schedule "30m"
# To pause: hermes cron pause heartbeat-<project_name>
# To resume: hermes cron resume heartbeat-<project_name>

# Resolve Hermes home the way core does — never hardcode an install layout.
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export HERMES_HOME
export HERMES_KANBAN_DB="${HERMES_KANBAN_DB:-$HERMES_HOME/kanban.db}"

# Prefer the interpreter that runs Hermes: a bare python3 from PATH is often
# Hermes' bundled tool Python, which cannot import hermes_cli.
PYTHON="${AGORA_PYTHON:-}"
if [ -z "$PYTHON" ]; then
    # First choice is the interpreter that generated this script (it is the one
    # Hermes runs under, so hermes_cli is importable); the rest are fallbacks.
    for p in "__AGORA_GEN_PYTHON__" "$HERMES_HOME/hermes-agent/venv/bin/python3" "$(command -v python3)"; do
        [ -x "$p" ] && PYTHON="$p" && break
    done
fi
[ -z "$PYTHON" ] && PYTHON=python3

# Hermes never runs on a correctly-chosen interpreter alone: its launcher puts
# the core tree on sys.path, and hermes_bootstrap ->
# pm.environments.activate_dependencies puts the selected environment's
# site-packages there too. A process spawned by cron inherits neither, so
# "$PYTHON" (Hermes' bundled tool Python) can import neither hermes_cli nor any
# third-party dependency on its own. Both paths were discovered from sys.path
# when this script was written — never guessed, so a layout that keeps core
# outside $HERMES_HOME/hermes-agent still resolves.
AGORA_CORE_ROOT="__AGORA_CORE_ROOT__"
AGORA_DEPS_DIRS="__AGORA_DEPS_DIRS__"
if [ -f "$AGORA_CORE_ROOT/hermes_cli/__init__.py" ]; then
    _agora_paths="$AGORA_CORE_ROOT"
    [ -n "$AGORA_DEPS_DIRS" ] && _agora_paths="$_agora_paths:$AGORA_DEPS_DIRS"
    export PYTHONPATH="${_agora_paths}${PYTHONPATH:+:$PYTHONPATH}"
elif ! "$PYTHON" -c "import hermes_cli" >/dev/null 2>&1; then
    # The baked path is gone and this interpreter cannot import core either, so
    # no heartbeat this script runs can read the kanban board. Say so and stop:
    # the completion gate would otherwise defer forever, which is
    # indistinguishable from a project that is still working. Only unreachable
    # when both routes fail, so an install that merely moved keeps running.
    echo "agora heartbeat: cannot import hermes_cli (baked core root: '$AGORA_CORE_ROOT')." >&2
    echo "This script is regenerated when a project starts; start one to pick up the new path." >&2
    exit 1
fi

# Locate the agora plugin directory — it must contain the agora/ submodule.
PLUGIN="${AGORA_PLUGIN_PATH:-}"
if [ -z "$PLUGIN" ]; then
    for d in "$HERMES_HOME/plugins/agora" "$(cd "$(dirname "$0")/.." && pwd)/plugins/agora"; do
        [ -d "$d/agora" ] && PLUGIN="$d" && break
    done
fi

if [ -z "$PLUGIN" ]; then
    echo "agora plugin directory not found; set AGORA_PLUGIN_PATH" >&2
    exit 1
fi

export AGORA_PLUGIN_PATH="$PLUGIN"
{
  "$PYTHON" - <<'PY'
import json, os, sys, types
from pathlib import Path

# Load the plugin the way Hermes does — as `hermes_plugins.agora` with its own
# search path — so the modules inside it resolve their relative imports. Bare
# top-level registration would strand every relative import that crosses a
# package boundary, and putting the plugin root on sys.path would shadow core's
# own tools/ and hooks/ packages.
_plugin_root = Path(os.environ["AGORA_PLUGIN_PATH"])
_ns = sys.modules.get("hermes_plugins")
if _ns is None:
    _ns = types.ModuleType("hermes_plugins")
    _ns.__path__ = []
    sys.modules["hermes_plugins"] = _ns

_pkg_name = "hermes_plugins.agora"
if _pkg_name not in sys.modules:
    _pkg = types.ModuleType(_pkg_name)
    _pkg.__path__ = [str(_plugin_root)]
    _pkg.__package__ = _pkg_name
    sys.modules[_pkg_name] = _pkg

from hermes_plugins.agora.agora.leader_loop import heartbeat
print(json.dumps(heartbeat(), indent=2))
PY
} 2>&1 | tail -10
"""
        _core_roots, _deps_dirs = capture_hermes_import_env()
        script_content = script_content.replace("__AGORA_GEN_PYTHON__", sys.executable)
        script_content = script_content.replace(
            "__AGORA_CORE_ROOT__", _core_roots[0] if _core_roots else ""
        )
        script_content = script_content.replace("__AGORA_DEPS_DIRS__", ":".join(_deps_dirs))
        if script_path.exists():
            try:
                if script_path.read_text() == script_content:
                    return
            except OSError:
                pass
        script_path.write_text(script_content)
        script_path.chmod(0o755)
        logger.info("Heartbeat script written to %s", script_path)
    except Exception as exc:
        logger.warning("Failed to create heartbeat script: %s", exc)


def _remove_heartbeat_cron(cron_id: str) -> None:
    """Remove a Hermes cron job by ID."""
    hermes = find_hermes_binary()
    try:
        cron_env = {**os.environ}
        cron_env["HERMES_HOME"] = str(get_global_root())
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
    allow_unattended: bool = False,
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
        allow_unattended:  Let workers and the leader run with approvals
                           bypassed (``--yolo --accept-hooks``). Default False:
                           a ``-q`` subprocess has nobody to answer an approval
                           prompt, so without this the team can read, discuss
                           and plan, but its file writes and shell commands are
                           denied. Enable only for a workdir you are willing to
                           let agents modify unattended.

    Returns:
        dict with status and project info
    """
    # Deploy the bundled skills (explicit user action — registration never
    # writes to disk). Idempotent; workers also fall back to the bundled copy.
    #
    # The import sits outside the try on purpose: a broken import is a code
    # defect and must be loud, not a warning. It was inside a bare
    # `except Exception` once, which is how `from .agora import …` (the wrong
    # package) stayed invisible while the deploy silently did nothing.
    from . import deploy_bundled_skills

    try:
        deployed = deploy_bundled_skills()
        if deployed:
            logger.info("Deployed bundled skills for project %s: %s", project_name, ", ".join(deployed))
        else:
            logger.info("No bundled skills to deploy for project %s", project_name)
    except Exception as exc:
        logger.warning("Skill deployment failed: %s", exc)

    # Ensure workdir exists
    import os
    if workdir and not os.path.exists(workdir):
        os.makedirs(workdir, exist_ok=True)
        logger.info("Created project workdir: %s", workdir)

    if allow_unattended:
        logger.warning(
            "Project '%s' started with allow_unattended=True — workers run with "
            "approvals bypassed. Their file writes and shell commands execute "
            "without prompting.",
            project_name,
        )

    pf = _project_file(project_name)
    board_name = _ensure_project_board(project_name)

    # Validate heartbeat_member if provided — runs for both new and
    # reactivated projects (M6 fix: previously only validated for new projects).
    if heartbeat_member:
        from .agora.worker_manager import get_worker
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
            # Opting in is explicit; a reactivate without the flag keeps whatever
            # the project already had (so a restart doesn't silently grant it).
            if allow_unattended:
                existing["allow_unattended"] = True
            # Recreate heartbeat cron if member is set and cron is missing or stale
            if existing.get("heartbeat_member"):
                old_cron_id = existing.get("heartbeat_cron_id")
                if old_cron_id:
                    # Verify the cron job still exists
                    import subprocess as _sp
                    _hermes = find_hermes_binary()
                    try:
                        _cron_env = {**os.environ}
                        _cron_env["HERMES_HOME"] = str(get_global_root())
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
        "last_heartbeat_at": None,
        "last_heartbeat_pid": None,
        # Leader PIDs still running for this project. The heartbeat gate reads
        # this so a cron fire cannot stack a second leader on a running one;
        # see project_planner.live_heartbeat_pids.
        "live_heartbeat_pids": [],
        "complete_count": 0,
        "completion_check_pos": 0,
        "chat_root_id": None,  # 2.0 team channel task id (set below)
        # Whether workers/the leader may run with approvals bypassed. Off unless
        # the operator opts in when starting the project.
        "allow_unattended": bool(allow_unattended),
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
            from .agora.team_manager import _bind_team_to_project, get_team
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

    # 2.0: create the team chat root and subscribe all known workers.
    _ensure_chat_channel(project_name, board_name, team, heartbeat_member)

    # Write AGENTS.md to workdir so workers auto-load team context
    update_project_agents_md(project_name)

    return {"status": "started", "project": data}


def stop_project(project_name: str) -> dict:
    """Stop a project, pause its heartbeat, and delete all kanban tasks."""
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

    # Delete all kanban tasks — same as on_project_complete.
    # Without this, old tasks remain and confuse the leader on restart.
    try:
        from .agora.kanban_compat import kanban_db as _kdb
        board = agora_board_for(project_name)
        conn = _kdb.connect()
        try:
            # Strict tenant scope — never delete tasks that merely lack a tenant.
            rows = conn.execute(
                "SELECT id FROM tasks WHERE tenant = ?",
                (board,),
            ).fetchall()
            task_ids = [r[0] for r in rows]
            deleted = 0
            for tid in task_ids:
                _kdb.delete_archived_task(conn, tid)
                deleted += 1
            conn.commit()
            logger.info(
                "Project '%s' stopped: deleted %d kanban tasks",
                project_name, deleted,
            )
        finally:
            conn.close()
    except Exception as exc:
        logger.warning(
            "Failed to delete tasks on project stop: %s", exc
        )

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
            from .agora.team_manager import get_team
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
    from .agora.worker_manager import _worker_file
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


def project_allows_unattended(project_name: str | None) -> bool:
    """True when the project opted into approval-bypassing agents.

    Missing/unknown projects answer False, so a project that never set the flag
    (or an unresolvable one) keeps the safe default.
    """
    if not project_name:
        return False
    try:
        proj = get_project(project_name)
    except Exception:
        return False
    return bool((proj or {}).get("allow_unattended", False))


#: Prefix every Agora project board carries.
BOARD_PREFIX = "agora-"


def agora_board_for(project_name: str) -> str:
    """Board (kanban tenant) name for a project."""
    return f"{BOARD_PREFIX}{safe_name(project_name)}"


def is_agora_owned_task(task: Any) -> bool:
    """True when a kanban task belongs to an Agora project board.

    Used to keep task-scoped operations (close/complete/archive) inside the
    plugin's own board: without this an arbitrary task id would reach mechanism
    meant only for Agora's tasks. Resolution is strict when the project registry
    answers (the board must belong to a registered project) and falls back to
    the board prefix when it can't be read.
    """
    tenant = getattr(task, "tenant", "") or ""
    if not tenant.startswith(BOARD_PREFIX):
        return False
    try:
        boards = {agora_board_for(p.get("name", "")) for p in list_projects()}
    except Exception:
        return True
    if not boards:
        return True
    return tenant in boards


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
    from .agora.leader_loop import heartbeat
    return heartbeat(project=project_name)


def _pid_alive(pid: int) -> bool:
    """True when ``pid`` names a live process we are allowed to signal."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours
    except OSError:
        return False
    return True


#: How long a leader run may last before its entry stops counting as in-flight.
#: Liveness alone is not enough: PIDs are recycled, and a PID reused by an
#: unrelated long-lived process would keep the gate shut forever — the project
#: would never get another leader, which is worse than the pileup this gate
#: exists to prevent. Generous enough for a slow leader under model contention
#: (reported at 20+ minutes), bounded enough that a recycled PID cannot pin the
#: gate permanently.
_HEARTBEAT_MAX_RUNTIME_SECONDS = 2 * 60 * 60


def _heartbeat_entry(entry: Any) -> tuple[int, float] | None:
    """Normalise one recorded entry to ``(pid, started_at)``; None if unusable.

    Entries are dicts (``{"pid": …, "at": …}``). A bare int — the shape v2.0.10
    wrote for a few hours — carries no age, and an age we cannot check can never
    expire: treating such an entry as fresh would let a recycled PID pin the
    gate shut forever, which is the failure this whole mechanism exists to
    avoid. So an unverifiable entry is dropped instead. The cost is at most one
    redundant leader on the first heartbeat after upgrading; the next spawn
    writes a timestamped entry.
    """
    if not isinstance(entry, dict):
        return None
    pid = entry.get("pid")
    if not isinstance(pid, int):
        return None
    at = entry.get("at")
    if not isinstance(at, (int, float)):
        return None
    return pid, float(at)


def live_heartbeat_pids(project_name: str) -> list[int]:
    """This project's leader PIDs that are plausibly still running.

    The heartbeat cron fires on a fixed interval while a leader's own run can
    outlast it (model contention pushes a heartbeat past 20 minutes), so a fire
    that does not consult this list stacks another leader onto the same
    inference endpoint. Recording is append+prune rather than a single slot: two
    leaders can legitimately overlap momentarily, and dropping a still-running
    PID early is what produced the pileup.

    An entry counts only while it is both alive *and* within
    ``_HEARTBEAT_MAX_RUNTIME_SECONDS`` — see that constant for why liveness
    alone is not sufficient. Dead and expired entries are pruned from the
    registry as a side effect, so a stale entry cannot accumulate.
    """
    pf = _project_file(project_name)
    if not pf.exists():
        return []
    try:
        data = json.loads(pf.read_text())
    except (OSError, ValueError):
        return []
    recorded = data.get("live_heartbeat_pids") or []
    now = time.time()

    live: list[int] = []
    kept: list[dict] = []
    for entry in recorded:
        parsed = _heartbeat_entry(entry)
        if parsed is None:
            continue
        pid, started = parsed
        if not _pid_alive(pid) or (now - started) > _HEARTBEAT_MAX_RUNTIME_SECONDS:
            continue
        live.append(pid)
        kept.append({"pid": pid, "at": started})

    if kept != recorded:
        data["live_heartbeat_pids"] = kept
        try:
            pf.write_text(json.dumps(data, indent=2))
        except OSError:
            pass  # pruning is best-effort; the caller only needs the live list
    return live


def update_heartbeat_status(project_name: str, pid: int | None = None) -> None:
    """Update the last heartbeat timestamp for a project.

    ``pid`` is also recorded among the project's live leader PIDs, after
    dropping the ones that have exited. ``live_heartbeat_pids`` is what the
    heartbeat gate consults so a second leader is not spawned on top of a
    running one.
    """
    pf = _project_file(project_name)
    if not pf.exists():
        return
    data = json.loads(pf.read_text())
    data["last_heartbeat_at"] = now_iso()
    data["last_heartbeat_pid"] = pid
    if pid is not None:
        now = time.time()
        recorded = []
        for entry in (data.get("live_heartbeat_pids") or []):
            parsed = _heartbeat_entry(entry)
            if parsed is None:
                continue
            old_pid, started = parsed
            if _pid_alive(old_pid) and (now - started) <= _HEARTBEAT_MAX_RUNTIME_SECONDS:
                recorded.append({"pid": old_pid, "at": started})
        recorded.append({"pid": pid, "at": now})
        seen: dict[int, float] = {}
        for item in recorded:
            seen[item["pid"]] = max(seen.get(item["pid"], 0.0), item["at"])
        data["live_heartbeat_pids"] = [
            {"pid": p, "at": t} for p, t in sorted(seen.items())
        ]
    pf.write_text(json.dumps(data, indent=2))


def get_heartbeat_member(project_name: str) -> str | None:
    """Get the heartbeat member (leader) for a project."""
    proj = get_project(project_name)
    if proj is None:
        return None
    return proj.get("heartbeat_member")


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
            from .agora.kanban_compat import kanban_db as _kdb
            board = agora_board_for(project_name)
            conn = _kdb.connect()
            try:
                # Get all task IDs for this project
                rows = conn.execute(
                    "SELECT id FROM tasks WHERE tenant = ?",
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
        get_global_root() / "cron" / "jobs.json",
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
    from .agora.worker_manager import _worker_file
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
        from .agora.kanban_compat import kanban_db
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
        from .agora.kanban_compat import kanban_db
        from .agora.utils import PENDING_TASK_STATUSES

        placeholders = ", ".join("?" * len(PENDING_TASK_STATUSES))
        conn = kanban_db.connect()
        try:
            if project_name:
                tenant = agora_board_for(project_name)
                rows = conn.execute(
                    f"SELECT COUNT(*) as n FROM tasks WHERE status IN ({placeholders}) AND tenant = ?",
                    (*PENDING_TASK_STATUSES, tenant),
                ).fetchone()
            else:
                rows = conn.execute(
                    f"SELECT COUNT(*) as n FROM tasks WHERE status IN ({placeholders})",
                    PENDING_TASK_STATUSES,
                ).fetchone()
            return rows["n"] > 0
        finally:
            conn.close()
    except Exception:
        return False
