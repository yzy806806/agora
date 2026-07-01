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
        "-Q",               # quiet mode: only final response + session info
    ]
    if session_id:
        cmd.extend(["--resume", session_id])
    cmd.extend(["chat", "-q", prompt])

    # Build environment
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)

    # Set workdir via TERMINAL_CWD
    if workdir and os.path.isabs(workdir) and os.path.isdir(workdir):
        env["TERMINAL_CWD"] = workdir

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


def _extract_reply(text: str) -> str:
    """Extract the content after DISCUSSION_REPLY: marker."""
    idx = text.find(REPLY_MARKER)
    if idx == -1:
        return ""
    reply = text[idx + len(REPLY_MARKER):].strip()
    # Strip trailing session_id line if present
    reply = re.sub(r"\nsession_id:\s*\S+$", "", reply).strip()
    return reply
