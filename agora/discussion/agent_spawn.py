"""Spawn real Hermes profile agents for Agora discussions.

Each "speak" in a discussion is a real `hermes -p <profile> chat -q` subprocess —
not a stateless ctx.llm.complete call. This means the agent has:

  - SOUL.md (role identity)
  - MEMORY.md (accumulated experience)
  - Tools (terminal, read_file, web_search, skill_manage, ...)
  - Session context (when --resume is used, full conversation history)

This is the difference between "an actor pretending to be the Developer" and
"actually calling the Developer into the meeting".
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from ..utils import find_hermes_binary

logger = logging.getLogger(__name__)

# Marker the agent must use to delimit its discussion reply.
REPLY_MARKER = "DISCUSSION_REPLY:"

# Stderr pattern for session_id (Hermes writes "session_id: <id>" on exit).
SESSION_ID_PATTERN = re.compile(r"session_id:\s*(\S+)")


def spawn_agent_speak(
    profile_name: str,
    prompt: str,
    *,
    session_id: str | None = None,
    workdir: str | None = None,
    timeout: int = 300,
    extra_env: dict[str, str] | None = None,
) -> dict:
    """Spawn a Hermes profile agent to respond to a discussion prompt.

    Args:
        profile_name:  Hermes profile name (e.g. "alice", "leader-1")
        prompt:        The full discussion prompt to send
        session_id:    If given, --resume this session to keep conversation context
        workdir:       Working directory for the agent (project dir)
        timeout:       Max seconds to wait (default 300 = 5 min)
        extra_env:     Additional environment variables

    Returns:
        dict with keys:
          reply:       str  — the agent's discussion reply text
          session_id:  str  — session ID for future --resume
          error:       str|None
    """
    hermes_bin = find_hermes_binary()

    cmd = [
        hermes_bin,
        "-p", profile_name,
        "--yolo",           # bypass command approval (unattended)
        "--accept-hooks",   # auto-approve shell hooks
        "--toolsets", "agora",  # agora tools for discussion (raise_motion, etc.)
    ]
    if session_id:
        cmd.extend(["--resume", session_id])
    cmd.extend(["chat", "-Q", "-q", prompt])  # -Q after chat (subcommand flag)

    # Build environment
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)

    # Set workdir via TERMINAL_CWD
    if workdir and os.path.isabs(workdir) and os.path.isdir(workdir):
        env["TERMINAL_CWD"] = workdir

    # Set HERMES_KANBAN_BOARD if the project has a dedicated board.
    # This gives agents project-scoped kanban isolation.  We try to
    # look up the board name from the project registry via the workdir
    # or project name.  The caller can also pass it directly via extra_env.
    if "HERMES_KANBAN_BOARD" not in env:
        _set_project_board_env(env, workdir)

    logger.info(
        "Spawning agent: profile=%s session=%s timeout=%ds",
        profile_name, session_id or "(new)", timeout,
    )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=workdir if workdir and os.path.isabs(workdir) and os.path.isdir(workdir) else None,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Agent %s timed out after %ds", profile_name, timeout)
        return {
            "reply": "",
            "session_id": session_id or "",
            "error": f"Agent timed out after {timeout}s",
        }
    except Exception as exc:
        logger.error("Failed to spawn agent %s: %s", profile_name, exc)
        return {
            "reply": "",
            "session_id": session_id or "",
            "error": str(exc),
        }

    stdout = result.stdout or ""
    stderr = result.stderr or ""

    # Extract session_id from stderr
    new_session_id = session_id or ""
    sid_match = SESSION_ID_PATTERN.search(stderr)
    if sid_match:
        new_session_id = sid_match.group(1)

    # Extract reply after DISCUSSION_REPLY: marker
    reply = _extract_reply(stdout)

    if not reply:
        # If no marker found, use the full stdout as fallback
        # (agent may not have followed the marker convention)
        reply = stdout.strip()
        if not reply and stderr:
            reply = f"[Agent error: {stderr.strip()[:200]}]"

    logger.info(
        "Agent %s responded (session=%s, reply_len=%d)",
        profile_name, new_session_id, len(reply),
    )

    return {
        "reply": reply,
        "session_id": new_session_id,
        "error": None if reply else "Empty response",
    }


def spawn_chair_speak(
    chair_profile: str,
    prompt: str,
    *,
    workdir: str | None = None,
    timeout: int = 120,
) -> dict:
    """Spawn the chair (Leader) agent for meta-decisions.

    Chair calls are typically shorter (evaluate/summarize), so a shorter
    timeout is used. The chair does NOT need --resume because each chair
    call is an independent meta-decision, not a continuous conversation.
    """
    return spawn_agent_speak(
        profile_name=chair_profile,
        prompt=prompt,
        session_id=None,  # chair calls are stateless meta-decisions
        workdir=workdir,
        timeout=timeout,
    )


def _set_project_board_env(env: dict[str, str], workdir: str | None) -> None:
    """Look up the project's kanban board name and set HERMES_KANBAN_BOARD.

    Tries to find a project whose workdir matches, then reads its ``board``
    field.  Falls back gracefully if the project registry can't be read.
    """
    try:
        import json
        from ..utils import get_registry_dir
        projects_dir = get_registry_dir("projects")
        for pf in projects_dir.glob("*.json"):
            try:
                proj = json.loads(pf.read_text())
                # Match by workdir or by board field existence
                if workdir and proj.get("workdir") == workdir:
                    board = proj.get("board")
                    if board:
                        env["HERMES_KANBAN_BOARD"] = board
                        return
            except Exception:
                continue
    except Exception:
        pass  # non-fatal — agents just won't have board-scoped kanban


def _extract_reply(text: str) -> str:
    """Extract the content after DISCUSSION_REPLY: marker."""
    idx = text.find(REPLY_MARKER)
    if idx == -1:
        return ""
    reply = text[idx + len(REPLY_MARKER):].strip()
    # Strip trailing session_id line if present
    reply = re.sub(r"\nsession_id:\s*\S+$", "", reply).strip()
    return reply


# --------------------------------------------------------------------------- #
#  spawn_discussion_driver — shared background-spawn for DiscussionDriver     #
# --------------------------------------------------------------------------- #

def spawn_discussion_driver(
    motion_id: str,
    chair: str,
    participants: list[str],
    workdir: str = "",
    project_name: str = "",
    max_steps: int = 30,
) -> dict:
    """Spawn the DiscussionDriver as a background process.

    Writes a runner script to ``~/.hermes/agora/run_discussion_<motion_id>.py``
    and Popen's it with stdout/stderr redirected to a log file.  This is the
    shared spawn logic used by both the ``/agora`` tool (``agora_raise_motion``)
    and the dashboard's ``start_discussion`` endpoint.

    Args:
        motion_id:     The motion to discuss.
        chair:         Chair (leader) profile name.
        participants:  List of worker profile names.
        workdir:       Working directory for the discussion.
        project_name:  Project name (for logging/context).
        max_steps:     Max discussion steps.

    Returns:
        dict with keys:
          - status:   "spawned" | "error"
          - log:      path to the log file (str)
          - runner:   path to the runner script (str)
          - error:    error message (only when status == "error")
    """
    import os
    import sys
    from pathlib import Path

    try:
        # Determine the agora plugin root for sys.path insertion in the runner
        # agent_spawn.py lives at <plugin_root>/agora/discussion/agent_spawn.py
        plugin_root = Path(__file__).resolve().parent.parent.parent

        # Determine HERMES_HOME for the runner/log paths
        hermes_home = os.environ.get(
            "HERMES_HOME", str(Path.home() / ".hermes"),
        )
        agora_dir = Path(hermes_home) / "agora"
        agora_dir.mkdir(parents=True, exist_ok=True)

        runner_path = agora_dir / f"run_discussion_{motion_id}.py"
        log_path = agora_dir / f"discussion_{motion_id}.log"

        # Build the runner script content
        # Use repr() for safe string embedding
        runner_script = f'''\
#!/usr/bin/env python3
"""Auto-generated discussion runner for motion {motion_id}."""
import sys, importlib.util
from pathlib import Path

_plugin_root = Path({str(plugin_root)!r})
_agora_pkg = _plugin_root / "agora"

# Register the agora package without polluting sys.path
if "agora" not in sys.modules and _agora_pkg.is_dir():
    _spec = importlib.util.spec_from_file_location(
        "agora", _agora_pkg / "__init__.py",
        submodule_search_locations=[str(_agora_pkg)],
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["agora"] = _mod
    _spec.loader.exec_module(_mod)

# Register project_planner (top-level module)
if "project_planner" not in sys.modules:
    _pp = _plugin_root / "project_planner.py"
    if _pp.exists():
        _spec = importlib.util.spec_from_file_location("project_planner", _pp)
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules["project_planner"] = _mod
        _spec.loader.exec_module(_mod)

from agora.discussion.driver import DiscussionDriver
driver = DiscussionDriver(
    motion_id={motion_id!r},
    chair_profile={chair!r},
    participants={participants!r},
    workdir={workdir!r},
    project_name={project_name!r},
    max_steps={max_steps!r},
)
result = driver.run()
print(f"Discussion result: {{result.decision}} ({{result.steps_completed}} steps)")
'''
        runner_path.write_text(runner_script)

        # Spawn it in the background
        log_fd = open(log_path, "a")
        _proc = subprocess.Popen(
            ["python3", str(runner_path)],
            stdout=log_fd,
            stderr=log_fd,
            start_new_session=True,
            cwd=workdir if workdir and os.path.isabs(workdir) and os.path.isdir(workdir) else None,
        )

        logger.info(
            "Discussion driver spawned for motion %s (PID %s, log=%s)",
            motion_id, _proc.pid, log_path,
        )
        return {
            "status": "spawned",
            "log": str(log_path),
            "runner": str(runner_path),
        }
    except Exception as exc:
        logger.error("Failed to spawn discussion driver for motion %s: %s", motion_id, exc)
        return {
            "status": "error",
            "log": str(log_path) if "log_path" in locals() else "",
            "runner": str(runner_path) if "runner_path" in locals() else "",
            "error": str(exc),
        }
