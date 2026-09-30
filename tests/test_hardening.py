"""Regression tests for the catalog-admission hardening pass.

Each test pins a boundary that the plugin reached outside its own sandbox:

* plugin code must not put its own root on ``sys.path`` (it would shadow core's
  ``tools`` package) and must still be importable as a package;
* worker/leader subprocesses only get ``--yolo --accept-hooks`` when the project
  opted in;
* the worker profile's ``.env`` is copied, not symlinked;
* task-scoped kanban operations refuse tasks outside the plugin's board.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from hermes_plugins.agora.agora.discussion import agent_spawn
from hermes_plugins.agora.agora.kanban_compat import kanban_db as kb
from hermes_plugins.agora.agora import motion as motion_mod
from hermes_plugins.agora.agora import chat
from hermes_plugins.agora import project_planner
from hermes_plugins.agora.agora.worker_manager import _copy_global_env

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Packaging: no sys.path pollution, package imports still resolve             #
# --------------------------------------------------------------------------- #

def test_plugin_root_not_on_sys_path():
    """Importing the plugin must not insert its root into sys.path.

    The root contains ``tools/``, ``hooks/`` and ``skills/``, all of which core
    also has; putting it on sys.path shadows them. Checked in a subprocess so
    the assertion reflects the plugin's behaviour rather than pytest's own
    import machinery.
    """
    import subprocess

    code = (
        "import sys, types\n"
        "root = sys.argv[1]\n"
        "ns = types.ModuleType('hermes_plugins'); ns.__path__ = []; sys.modules['hermes_plugins'] = ns\n"
        "pkg = types.ModuleType('hermes_plugins.agora'); pkg.__path__ = [root]\n"
        "pkg.__package__ = 'hermes_plugins.agora'; sys.modules['hermes_plugins.agora'] = pkg\n"
        "import hermes_plugins.agora.tools\n"
        "import hermes_plugins.agora.project_planner\n"
        "print('POLLUTED' if root in sys.path else 'CLEAN')\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code, str(_PLUGIN_ROOT)],
        capture_output=True, text=True, timeout=120, cwd="/tmp",
    )
    assert out.returncode == 0, out.stderr
    assert "CLEAN" in out.stdout, out.stdout + out.stderr


def test_plugin_modules_import_through_package():
    """Modules that cross a package boundary resolve relative imports."""
    import importlib

    for name in (
        "hermes_plugins.agora.project_planner",
        "hermes_plugins.agora.tools",
        "hermes_plugins.agora.hooks",
        "hermes_plugins.agora.agora.leader_loop",
        "hermes_plugins.agora.agora.discussion.driver",
    ):
        assert importlib.import_module(name) is not None


# --------------------------------------------------------------------------- #
# Approvals: unattended operation is opt-in                                   #
# --------------------------------------------------------------------------- #

def _capture_agent_cmd(monkeypatch, **kwargs) -> list[str]:
    captured: dict[str, list[str]] = {}

    class _Done:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(cmd, **run_kwargs):
        captured["cmd"] = list(cmd)
        return _Done()

    monkeypatch.setattr(agent_spawn.subprocess, "run", _fake_run)
    agent_spawn._run_agent_subprocess(
        "hermes", "worker1", "prompt", None, None, 5, dict(os.environ), **kwargs
    )
    return captured["cmd"]


def test_agent_subprocess_defaults_to_no_bypass(monkeypatch):
    cmd = _capture_agent_cmd(monkeypatch)
    assert "--yolo" not in cmd
    assert "--accept-hooks" not in cmd
    assert cmd[:3] == ["hermes", "-p", "worker1"]


def test_agent_subprocess_bypasses_only_when_allowed(monkeypatch):
    cmd = _capture_agent_cmd(monkeypatch, allow_unattended=True)
    assert "--yolo" in cmd
    assert "--accept-hooks" in cmd


def test_start_project_tool_forwards_allow_unattended(monkeypatch):
    """The documented opt-in ``agora_start_project(allow_unattended=True)`` reaches the registry."""
    import asyncio

    from hermes_plugins.agora import tools as tools_mod

    registered: dict[str, dict] = {}

    class _Ctx:
        def register_tool(self, **kwargs):
            registered[kwargs["name"]] = kwargs

    tools_mod._register_project_tools(_Ctx())
    tool = registered["agora_start_project"]
    assert tool["schema"]["properties"]["allow_unattended"]["default"] is False

    seen: dict = {}
    monkeypatch.setattr(project_planner, "start_project", lambda **kw: seen.update(kw) or {"status": "ok"})
    asyncio.run(tool["handler"]({"name": "p", "workdir": "/x", "allow_unattended": True}))
    assert seen["allow_unattended"] is True
    asyncio.run(tool["handler"]({"name": "p", "workdir": "/x"}))
    assert seen["allow_unattended"] is False


def test_project_defaults_to_unattended_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(project_planner, "get_registry_dir", lambda name: _mk(tmp_path, name))
    assert project_planner.project_allows_unattended("") is False
    assert project_planner.project_allows_unattended("never-started") is False


def _mk(tmp_path, name):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- #
# Credentials: .env is copied, never symlinked                                #
# --------------------------------------------------------------------------- #

def test_global_env_is_copied_not_symlinked(tmp_path):
    home = tmp_path / "hermes"
    home.mkdir()
    (home / ".env").write_text("OPENAI_API_KEY=secret-value\n")

    profile = tmp_path / "profiles" / "worker1"
    profile.mkdir(parents=True)
    _copy_global_env(profile, home)

    target = profile / ".env"
    assert target.exists()
    assert not target.is_symlink(), "a symlink lets the worker rewrite the real keys"
    assert target.read_text() == "OPENAI_API_KEY=secret-value\n"
    # copy2 preserves source mode bits, so the copy is tightened explicitly.
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_global_env_symlink_is_migrated(tmp_path):
    """A symlink created by an older version is replaced with a real copy."""
    home = tmp_path / "hermes"
    home.mkdir()
    real = home / ".env"
    real.write_text("KEY=v\n")

    profile = tmp_path / "profiles" / "worker1"
    profile.mkdir(parents=True)
    (profile / ".env").symlink_to(real)

    _copy_global_env(profile, home)

    assert not (profile / ".env").is_symlink()
    assert (profile / ".env").read_text() == "KEY=v\n"


# --------------------------------------------------------------------------- #
# Kanban scope: stay on the plugin's own board                                #
# --------------------------------------------------------------------------- #

def test_is_agora_owned_task():
    class T:
        def __init__(self, tenant):
            self.tenant = tenant

    assert project_planner.is_agora_owned_task(T("agora-demo")) is True
    assert project_planner.is_agora_owned_task(T("")) is False
    assert project_planner.is_agora_owned_task(T(None)) is False
    assert project_planner.is_agora_owned_task(T("someone-elses-board")) is False


@pytest.fixture()
def board_conn(tmp_path):
    board = f"agora-hardening-{os.getpid()}-{tmp_path.name}"
    c = kb.connect(board=board)
    yield c, board
    try:
        c.execute("DELETE FROM tasks WHERE tenant = ?", (board,))
        c.commit()
    finally:
        c.close()


def test_close_motion_refuses_foreign_task(board_conn):
    """The raw done-flip must not touch a task that isn't an Agora motion."""
    c, board = board_conn
    foreign = kb.create_task(
        c, title="Just a normal task", body="", tenant=board,
    )
    c.commit()
    with pytest.raises(ValueError, match="not an Agora motion"):
        motion_mod.close_motion(c, motion_id=foreign, decision="superseded")


def test_close_motion_accepts_real_motion(board_conn):
    c, board = board_conn
    root = chat.ensure_chat_root(c, project_name="demo", tenant=board)
    mid = motion_mod.create_motion(
        c, chat_root_id=root, title="Pick a DB", participants=["a"], chair="leader",
        tenant=board,
    )
    motion_mod.add_speech(
        c, motion_id=mid, role="a", round_num=1, stance="support",
        content="use postgres",
    )
    motion_mod.close_motion(c, motion_id=mid, decision="adopted", rationale="agreed")
    c.commit()

    task = kb.get_task(c, mid)
    assert task.status == "done"
    assert json.loads(task.result)["decision"] == "adopted"


def test_close_motion_accepts_motion_whose_title_was_edited(board_conn):
    """The metadata comment is the second ownership marker.

    A title renamed outside Agora must not make the motion uncloseable — the
    driver finalizes through this path.
    """
    c, board = board_conn
    root = chat.ensure_chat_root(c, project_name="demo", tenant=board)
    mid = motion_mod.create_motion(
        c, chat_root_id=root, title="Pick a DB", participants=["a"], chair="leader",
        tenant=board,
    )
    c.execute("UPDATE tasks SET title = ? WHERE id = ?", ("renamed by hand", mid))
    c.commit()

    motion_mod.close_motion(c, motion_id=mid, decision="superseded")
    c.commit()
    assert kb.get_task(c, mid).status == "done"


# --------------------------------------------------------------------------- #
# Generated artifacts must actually parse in their own shells                 #
# --------------------------------------------------------------------------- #

def test_heartbeat_script_is_valid_bash(tmp_path, monkeypatch):
    """The generated heartbeat script has to be valid shell.

    It is executed by Hermes' cron runner, so a syntax error silently produces
    no heartbeat at all.
    """
    import subprocess

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    project_planner._ensure_heartbeat_script()

    script = tmp_path / "scripts" / "leader_heartbeat.sh"
    assert script.is_file()
    check = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert check.returncode == 0, check.stderr
    # The interpreter that generated it is preferred over a bare python3.
    assert sys.executable in script.read_text()


def test_discussion_runner_is_valid_python(tmp_path, monkeypatch):
    """The generated runner must compile and import through the package path."""
    import py_compile

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)

    class _FakePopen:
        def __init__(self, *a, **k):
            self.pid = 1

    monkeypatch.setattr(agent_spawn.subprocess, "Popen", _FakePopen)
    res = agent_spawn.spawn_discussion_driver(
        motion_id="m-test", chair="leader", participants=["dev"],
        workdir=str(tmp_path), project_name="demo", max_steps=1,
    )
    assert res["status"] == "spawned"
    runner = Path(res["runner"])
    py_compile.compile(str(runner), doraise=True)
    body = runner.read_text()
    assert "from hermes_plugins.agora.agora.discussion.driver import DiscussionDriver" in body
    assert "sys.path.insert" not in body


# --------------------------------------------------------------------------- #
# Board names come from one place                                             #
# --------------------------------------------------------------------------- #

def test_agora_board_for_normalizes_project_names():
    assert project_planner.agora_board_for("doc-mind") == "agora-doc-mind"
    # A name safe_name() rewrites must still produce the registry's board:
    # otherwise the task lands outside the project's scope.
    assert project_planner.agora_board_for("My Project") == "agora-My_Project"
    assert project_planner.agora_board_for("a/b") == "agora-a-b"


def test_board_names_have_a_single_construction_site():
    """Nothing may hand-build a board name.

    `agora_board_for` is the one place `agora-<project>` is assembled. A second
    construction site that skips `safe_name()` silently creates tasks the
    project cannot see, clean up or close.
    """
    import re

    root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or "tests" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r'''f"agora-\{''', line) or re.search(r'''f'agora-\{''', line):
                offenders.append(f"{path.relative_to(root)}:{lineno}")
    assert not offenders, (
        "build board names with project_planner.agora_board_for(); "
        f"found literal construction at {offenders}"
    )


def test_no_kanban_query_matches_a_missing_tenant():
    """Every board-scoped query must filter on tenant exactly.

    `WHERE (tenant = ? OR tenant IS NULL)` reaches past the plugin's own board:
    Agora always sets the tenant when it creates a task, so a NULL tenant means
    the task belongs to someone else. Four sites shipped that way across
    v2.0.x — the counts fed project status (a foreign task kept PROJECT_COMPLETE
    from ever firing) and stop_project's cleanup *deleted* foreign tasks.
    """
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or "tests" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            # Same SQL predicate, whitespace aside.
            if "tenant IS NULL" in line:
                offenders.append(f"{path.relative_to(root)}:{lineno}")
    assert not offenders, (
        "match the board exactly (tenant = ?); a NULL tenant is someone else's "
        f"task: {offenders}"
    )


def test_dashboard_resolves_the_kanban_db_from_the_shared_root(tmp_path, monkeypatch):
    """The dashboard must read the board the dispatcher writes to.

    ``kanban_db_path()`` resolves through ``kanban_home()``: ``HERMES_KANBAN_HOME``
    else the *default* root — deliberately not the active profile's
    ``HERMES_HOME``, because the board is shared across profiles and a
    profile-scoped path would fork it and break the dispatcher/worker handoff.

    The old fallback hardcoded ``<home>/kanban.db`` from ``Path.home()``, which is
    wrong on any install whose Hermes home is not ``~/.hermes``. This pins the
    resolution to core's own resolver, so the dashboard can never drift from it.
    """
    import importlib.util as ilu
    import types as _types

    root = Path(__file__).resolve().parent.parent
    # The knob core's resolver actually honours.
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)

    spec = ilu.spec_from_file_location(
        "hermes_plugins.agora.dashboard.plugin_api", root / "dashboard" / "plugin_api.py",
    )
    assert spec is not None and spec.loader is not None
    dash = _types.ModuleType("hermes_plugins.agora.dashboard")
    dash.__path__ = [str(root / "dashboard")]
    sys.modules["hermes_plugins.agora.dashboard"] = dash
    mod = ilu.module_from_spec(spec)
    mod.__package__ = "hermes_plugins.agora.dashboard"
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except ImportError:
        pytest.skip("FastAPI not importable in this environment")

    resolved = mod._kanban_db_path()

    from hermes_cli.kanban_db import kanban_db_path

    assert resolved == str(kanban_db_path()), (
        f"the dashboard reads {resolved!r} but core resolves the board to "
        f"{kanban_db_path()!r} — the two would count different databases"
    )
    assert resolved.startswith(str(tmp_path))


def test_nothing_trips_the_agent_config_shell_scan():
    """No file may contain a shell redirect into the agent context file.

    `hermes plugins validate`'s security scan reads `<x> > .../AGENTS.md` as a
    shell write into the agent's context file and fails the build on it. An
    angle-bracket placeholder immediately before the filename trips it
    (`<workdir>/AGENTS.md`), which is easy to write by accident in docs — so
    this scans every shipped text file, not just the sources.
    """
    import re

    # Same shape the scanner looks for. Tests are excluded: this file spells the
    # pattern out on purpose.
    pattern = re.compile(r'[\w"\'`)\]]\s*>\s*[~\w./-]*' + "AGENTS" + r"\.md")
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or ".git" in path.parts:
            continue
        if "tests" in path.parts:
            continue
        if path.suffix not in (".md", ".py", ".js", ".yaml", ".txt", ".json"):
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(root)}:{lineno}")
    assert not offenders, (
        "these lines trip the security scan's agent_config_mod_shell rule; "
        f"write the context-file path without a preceding `>`: {offenders}"
    )


# --------------------------------------------------------------------------- #
# The documented start-project path has to work end to end                    #
# --------------------------------------------------------------------------- #

def test_deploy_bundled_skills_lives_on_the_package_not_the_subpackage():
    """`deploy_bundled_skills` is defined in the plugin package's __init__.

    `start_project` used `from .agora import deploy_bundled_skills` — the inner
    subpackage, which does not define it. The surrounding `except Exception`
    swallowed the ImportError, so the documented "bundled skills deploy when a
    project starts" path logged a warning and did nothing. With register() no
    longer deploying them, that was the only automatic path left.
    """
    import importlib

    inner = importlib.import_module("hermes_plugins.agora.agora")
    assert not hasattr(inner, "deploy_bundled_skills"), "the inner package should not define it"
    assert hasattr(importlib.import_module("hermes_plugins.agora"), "deploy_bundled_skills")


def test_start_project_deploys_bundled_skills(tmp_path, monkeypatch):
    """Calling start_project must actually deploy the skills, not just log."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)

    project_planner.start_project(
        project_name="deploy-check", workdir=str(tmp_path / "work"), goal="dummy",
    )

    skill = tmp_path / "skills" / "collaboration" / "agora-awareness" / "SKILL.md"
    assert skill.is_file(), "bundled skills were not deployed on project start"

