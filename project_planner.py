"""Self-driving project loop — the planner that keeps Agora autonomous.

When a kanban task created by Agora completes, this module:
  1. Checks if there are still pending (todo/ready) tasks on the board.
     → If yes: do nothing, the kanban dispatcher will pick them up.
     → If no (all tasks done): enter the planning phase.
  2. Planning phase: spawn a lightweight agent that analyzes the project
     state (git log, test results, past discussions) and decides:
     → Project is complete → notify the user, stop.
     → Need another round → raise a new Agora motion → action items →
       new kanban tasks → dispatcher picks them up → loop continues.

The planner runs as a subprocess (``hermes chat -q``) so it has full
agent capabilities (tools, LLM, file access) without blocking the hook.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project registry — tracks which projects are in self-drive mode
# ---------------------------------------------------------------------------

_REGISTRY_DIR: Path | None = None


def _registry_dir() -> Path:
    """Return the directory for self-drive project registry files.

    Uses the GLOBAL Hermes home (not profile-scoped) so that workers
    running under different profiles (architect/developer/reviewer) can
    all find the same project registry. The kanban DB is already global
    (HERMES_KANBAN_DB=/root/.hermes/kanban.db), so the registry must be too.
    """
    global _REGISTRY_DIR
    if _REGISTRY_DIR is not None:
        return _REGISTRY_DIR
    kanban_db = os.environ.get("HERMES_KANBAN_DB", "")
    if kanban_db:
        global_root = str(Path(kanban_db).parent)
    else:
        try:
            from hermes_constants import get_hermes_home
            home = Path(get_hermes_home())
            if home.name == "profiles" or home.parent.name == "profiles":
                global_root = str(home.parent.parent)
            else:
                global_root = str(home)
        except Exception:
            global_root = str(Path.home() / ".hermes")
    d = Path(global_root) / "agora" / "projects"
    d.mkdir(parents=True, exist_ok=True)
    _REGISTRY_DIR = d
    return d


def _project_file(project_name: str) -> Path:
    """Return the registry file path for a project."""
    safe = project_name.replace("/", "-").replace(" ", "_")
    return _registry_dir() / f"{safe}.json"


def start_project(
    project_name: str,
    workdir: str,
    goal: str = "",
    initial_topic: str = "",
    profile: str = "coder",
    max_rounds: int = 10,
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
        "created_at": _now_iso(),
        "initial_topic": initial_topic,
        "last_planner_pid": None,
        "last_planner_at": None,
    }
    pf.write_text(json.dumps(data, indent=2))
    logger.info("Project %s started: %s", project_name, workdir)

    # Kick off the first planning cycle in a background thread
    # so start_project returns immediately without blocking the tool handler.
    import threading
    t = threading.Thread(
        target=_spawn_planner,
        args=(project_name,),
        kwargs={"topic_hint": initial_topic},
        daemon=True,
    )
    t.start()
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
    d = _registry_dir()
    projects = []
    for f in d.glob("*.json"):
        try:
            projects.append(json.loads(f.read_text()))
        except Exception:
            pass
    return projects


# ---------------------------------------------------------------------------
# Planner spawn — called by hook or by start_project
# ---------------------------------------------------------------------------

_PLANNER_PROMPT_TEMPLATE = """You are the Agora project planner for project '{project_name}'.

Your job is to analyze the current state of the project and decide the next step.

## Instructions

1. First, check the kanban board: run `hermes kanban list` to see if there are
   any pending (todo/ready) tasks. If there are, do nothing — the dispatcher
   will pick them up automatically.

2. If all tasks are done (or there are none), analyze the project state:
   - Go to the project directory: `{workdir}`
   - Run `git log --oneline -20` to see recent commits
   - Run `find . -name '*.py' | head -30` to see the file structure
   - Check if tests pass: run the project's test command
   - Read any README or architecture docs

3. Decide:
   - If the project goal is achieved → respond with "PROJECT_COMPLETE" and
     a summary of what was accomplished.
   - If more work is needed → use the `agora_raise_motion` tool to start a
     new discussion about the next phase of development. The motion title
     should be specific and actionable, like "Implement user authentication
     and session management" or "Add export to PDF feature".

4. When raising a motion, include in the description:
   - What has been done so far (brief summary)
   - What needs to be done next and why
   - Any technical constraints or decisions to make

## Context
- Topic hint: {topic_hint}
- Project goal: {goal}
- Project workdir: {workdir}
- You have access to all Hermes tools including agora_raise_motion,
  agora_list_motions, file tools, and terminal.

Be decisive and specific. Don't ask questions — make a decision and act on it.
"""


def _spawn_planner(project_name: str, topic_hint: str = "") -> int | None:
    """Spawn a planner agent subprocess for the given project.

    This is fire-and-forget — the planner runs independently and may
    take several minutes (it calls LLM, analyzes code, raises motions).

    Returns the PID, or None on failure.
    """
    data = get_project(project_name)
    if data is None:
        logger.warning("Cannot spawn planner: project '%s' not found", project_name)
        return None

    if data.get("status") != "active":
        logger.info("Project '%s' is %s, skipping planner", project_name, data.get("status"))
        return None

    # Check round limit
    current_round = data.get("current_round", 0)
    max_rounds = data.get("max_rounds", 10)
    if current_round >= max_rounds:
        logger.info("Project '%s' reached max_rounds (%d), stopping", project_name, max_rounds)
        data["status"] = "completed"
        _project_file(project_name).write_text(json.dumps(data, indent=2))
        return None

    workdir = data.get("workdir", "")
    profile = data.get("profile", "coder")
    goal = data.get("goal", "")

    # Build the planner prompt
    prompt = _PLANNER_PROMPT_TEMPLATE.format(
        project_name=project_name,
        topic_hint=topic_hint or "(auto-generated)",
        goal=goal or "(not specified)",
        workdir=workdir,
    )

    # Find the hermes binary
    hermes_bin = _find_hermes_binary()
    if hermes_bin is None:
        logger.error("Cannot find hermes binary for planner subprocess")
        return None

    cmd = [hermes_bin, "-p", profile, "chat", "-q", prompt]

    env = dict(os.environ)
    if workdir and os.path.isabs(workdir):
        env["TERMINAL_CWD"] = workdir

    # CRITICAL: Set HERMES_HOME to the project owner's profile so the
    # planner subprocess reads the same config, tools, and agora DB as
    # the profile that started the project. The worker that fired this
    # hook may be running under a different profile (developer/architect),
    # but the planner must run as the project's profile (e.g. coder).
    try:
        from hermes_constants import get_hermes_home
        worker_home = get_hermes_home()
        # If the worker's home is profile-scoped, replace with the
        # project owner's profile path.
        if "/profiles/" in str(worker_home):
            base = str(worker_home).rsplit("/profiles/", 1)[0]
            env["HERMES_HOME"] = f"{base}/profiles/{profile}"
        else:
            env["HERMES_HOME"] = str(worker_home)
    except Exception:
        pass
    # Also pass HERMES_KANBAN_DB so the planner uses the same shared DB.
    kanban_db = os.environ.get("HERMES_KANBAN_DB", "")
    if kanban_db:
        env["HERMES_KANBAN_DB"] = kanban_db

    # Log the planner output to a file for debugging
    log_path = _registry_dir() / f"planner_{project_name}.log"

    try:
        log_fd = open(log_path, "a")
        proc = subprocess.Popen(
            cmd,
            stdout=log_fd,
            stderr=log_fd,
            env=env,
            cwd=workdir if workdir and os.path.isabs(workdir) else None,
            start_new_session=True,  # detach from parent process group
        )

        # Update registry
        data["last_planner_pid"] = proc.pid
        data["last_planner_at"] = _now_iso()
        data["current_round"] = current_round + 1
        _project_file(project_name).write_text(json.dumps(data, indent=2))

        logger.info(
            "Planner spawned for '%s' (PID %d, round %d/%d, log: %s)",
            project_name, proc.pid, current_round + 1, max_rounds, log_path,
        )
        return proc.pid
    except Exception as exc:
        logger.error("Failed to spawn planner for '%s': %s", project_name, exc)
        return None


def _find_hermes_binary() -> str | None:
    """Find the hermes executable path."""
    # Check common locations
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
    # Try PATH
    import shutil
    return shutil.which("hermes")


# ---------------------------------------------------------------------------
# Hook entry point — called by kanban_task_completed
# ---------------------------------------------------------------------------

def on_task_completed(task_id: str, **kwargs: Any) -> None:
    """Called when a kanban task completes.

    Checks if the completed task belongs to an Agora-managed project.
    If so, and if there are no more pending tasks, spawns a planner.
    """
    try:
        # Find which project this task belongs to by checking task body
        # or comments for "From Agora discussion" marker.
        project_name = _find_project_for_task(task_id)
        if project_name is None:
            return  # Not an Agora-managed task

        data = get_project(project_name)
        if data is None or data.get("status") != "active":
            return

        # Check if there are still pending tasks on the board
        if _has_pending_tasks():
            logger.info(
                "Project '%s': task %s done but pending tasks remain — "
                "waiting for dispatcher",
                project_name, task_id,
            )
            return

        # All tasks done — spawn planner for next round.
        # But first check if a planner is already running (race condition:
        # multiple workers completing simultaneously).
        if _planner_running(project_name):
            logger.info(
                "Project '%s': planner already running (PID %s), skipping",
                project_name, data.get("last_planner_pid"),
            )
            return

        logger.info(
            "Project '%s': all tasks done, spawning planner (round %d)",
            project_name, data.get("current_round", 0) + 1,
        )
        _spawn_planner(project_name)

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


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _planner_running(project_name: str) -> bool:
    """Check if a planner process is already running for this project."""
    data = get_project(project_name)
    if not data:
        return False
    pid = data.get("last_planner_pid")
    if not pid:
        return False
    try:
        os.kill(pid, 0)  # signal 0 = check existence
        return True
    except (ProcessLookupError, PermissionError):
        return False
