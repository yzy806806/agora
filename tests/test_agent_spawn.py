"""Tests for agora.discussion.agent_spawn._extract_reply."""
from __future__ import annotations

import subprocess
from pathlib import Path

from hermes_plugins.agora.agora.discussion import agent_spawn
from hermes_plugins.agora.agora.discussion.agent_spawn import _extract_reply


def test_extract_reply_with_marker():
    """Input with DISCUSSION_REPLY: marker → returns the content after it."""
    text = "some text\nDISCUSSION_REPLY: My reply content\n"
    result = _extract_reply(text)
    assert result == "My reply content"


def test_extract_reply_without_marker():
    """Input without the marker → returns empty string."""
    result = _extract_reply("just some text")
    assert result == ""


def test_extract_reply_with_trailing_session_id():
    """Trailing session_id line should be stripped from the reply."""
    text = "DISCUSSION_REPLY: My reply\nsession_id: abc123"
    result = _extract_reply(text)
    assert result == "My reply"


def test_extract_reply_empty():
    """Empty input → returns empty string."""
    result = _extract_reply("")
    assert result == ""


def _capture_cmd(monkeypatch, **kwargs):
    """Run _run_agent_subprocess with subprocess.run stubbed; return the argv it built."""
    seen = {}

    def fake_run(cmd, **_kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="DISCUSSION_REPLY: ok", stderr="session_id: s1")

    monkeypatch.setattr(agent_spawn.subprocess, "run", fake_run)
    agent_spawn._run_agent_subprocess("hermes", "alice", "hi", None, None, 5, {}, **kwargs)
    return seen["cmd"]


def test_spawn_uses_explicit_toolsets_not_the_hermes_cli_bundle(monkeypatch):
    """`hermes-cli` pulls in kanban_* toolsets that current Hermes refuses for -q sessions."""
    monkeypatch.delenv("AGORA_SPEAKER_TOOLSETS", raising=False)
    cmd = _capture_cmd(monkeypatch)
    toolsets = cmd[cmd.index("--toolsets") + 1]
    assert toolsets == agent_spawn.DEFAULT_SPEAKER_TOOLSETS
    assert "hermes-cli" not in toolsets.split(",")
    assert not any(name.startswith("kanban") for name in toolsets.split(","))


def test_spawn_toolsets_env_override(monkeypatch):
    monkeypatch.setenv("AGORA_SPEAKER_TOOLSETS", "file,web")
    cmd = _capture_cmd(monkeypatch)
    assert cmd[cmd.index("--toolsets") + 1] == "file,web"


def test_spawn_blank_env_override_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("AGORA_SPEAKER_TOOLSETS", "   ")
    cmd = _capture_cmd(monkeypatch)
    assert cmd[cmd.index("--toolsets") + 1] == agent_spawn.DEFAULT_SPEAKER_TOOLSETS


def test_spawn_unattended_flags_unchanged(monkeypatch):
    """The toolset change must not touch the approval gate."""
    assert "--yolo" not in _capture_cmd(monkeypatch)
    assert "--yolo" in _capture_cmd(monkeypatch, allow_unattended=True)


def test_default_speaker_toolsets_keep_memory():
    """Memory is why a worker is a team member rather than a role prompt.

    Dropping the ``hermes-cli`` bundle to avoid the kanban refusal must not quietly
    take worker memory with it: a speaker that cannot write MEMORY.md accumulates
    nothing across projects.
    """
    names = {t.strip() for t in agent_spawn.DEFAULT_SPEAKER_TOOLSETS.split(",")}
    assert "memory" in names
    assert {"terminal", "file", "web", "skills"} <= names


def test_no_source_line_spawns_with_the_hermes_cli_bundle():
    """Invariant: nothing outside tests may spawn with ``--toolsets hermes-cli``.

    That bundle carries ``kanban_*``, which a ``-q`` session refuses before the model
    is reached while still exiting 0 — the failure mode that closed every motion with
    ``error (0 steps)``. This guards the class, not just the one call site.
    """
    root = Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if "__pycache__" in rel.parts or rel.parts[0] == "tests":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if "--toolsets" in code and "hermes-cli" in code:
                offenders.append(f"{rel}:{lineno}")
    assert offenders == [], (
        "spawned processes must not ask for the hermes-cli bundle (it carries "
        f"kanban_* toolsets, refused in a -q session): {offenders}"
    )
