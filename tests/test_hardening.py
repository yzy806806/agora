"""Regression tests for the catalog-admission hardening pass.

Each test pins a boundary that the plugin reached outside its own sandbox:

* plugin code must not put its own root on ``sys.path`` (it would shadow core's
  ``tools`` package) and must still be importable as a package;
* worker/leader subprocesses only get ``--yolo --accept-hooks`` when the project
  opted in;
* worker profiles are provisioned by core, so the plugin never reads the user's
  ``.env`` itself (catalog rule 11);
* task-scoped kanban operations refuse tasks outside the plugin's board.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from hermes_plugins.agora.agora.discussion import agent_spawn
from hermes_plugins.agora.agora.kanban_compat import kanban_db as kb
from hermes_plugins.agora.agora import motion as motion_mod
from hermes_plugins.agora.agora import chat
from hermes_plugins.agora.agora import utils
from hermes_plugins.agora import project_planner

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
# Credentials: provisioned by core, never read by the plugin                   #
# --------------------------------------------------------------------------- #

def test_worker_provisioning_goes_through_core(tmp_path, monkeypatch):
    """Catalog rule 11: credentials come through Hermes, never from files.

    The plugin must not read the global ``.env`` itself. Core's own profile
    provisioning copies ``config.yaml`` and ``.env`` (tightening the copy to
    owner-only), so the plugin asks for a profile and touches no credential file.
    """
    from hermes_plugins.agora.agora import worker_manager

    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_KANBAN_DB", str(hermes_home / "kanban.db"))
    (hermes_home / ".env").write_text("OPENAI_API_KEY=secret-value\n")

    copies: list = []
    for attr in ("copy2", "copy", "copyfile"):
        monkeypatch.setattr(
            worker_manager.shutil, attr,
            lambda *a, _attr=attr, **k: copies.append((_attr, a)),
        )
    calls = _stand_in_for_profile_create(monkeypatch)

    res = worker_manager.create_worker(name="probe", role="developer")

    assert res.get("status") == "created", res
    cmd = calls[0]["cmd"]
    assert cmd[:3] == ["hermes", "profile", "create"], cmd
    # Delegated, not hand-rolled: core does the cloning.
    #
    # `--no-skills` must NOT ride along: core refuses it with any clone option
    # ("--no-skills is mutually exclusive with --clone / --clone-from /
    # --clone-all"), and this test previously asserted the pairing, which is how
    # `agora_create_worker` stayed broken from v2.0.12 to v2.0.13 while the suite
    # stayed green. The skills the clone copies are dropped afterwards instead.
    assert "--clone-from" in cmd, cmd
    assert cmd[cmd.index("--clone-from") + 1] == "default", cmd
    assert "--no-skills" not in cmd, cmd
    assert "--clone" not in cmd, "--clone-from already implies the clone"
    # The global root is the clone source, so the worker inherits the keys.
    assert calls[0]["env"]["HERMES_HOME"] == str(hermes_home)
    # And the plugin copied no credential file itself.
    assert [c for c in copies if str(c[1][0]).endswith(".env")] == [], copies


def test_clone_from_path_asks_for_that_source(tmp_path, monkeypatch):
    """An explicit source still goes through core, with that profile named."""
    from hermes_plugins.agora.agora import worker_manager

    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_KANBAN_DB", str(hermes_home / "kanban.db"))
    calls = _stand_in_for_profile_create(monkeypatch)

    res = worker_manager.create_worker(
        name="probe2", role="developer", clone_from="default",
    )

    assert res.get("status") == "created", res
    assert "--clone-from" in calls[0]["cmd"], calls[0]["cmd"]
    assert "default" in calls[0]["cmd"], calls[0]["cmd"]


def test_templated_role_replaces_the_cloned_soul(tmp_path, monkeypatch):
    """A role worker gets its template's SOUL.md, not the operator's."""
    from hermes_plugins.agora.agora import worker_manager

    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_KANBAN_DB", str(hermes_home / "kanban.db"))
    _stand_in_for_profile_create(monkeypatch)

    res = worker_manager.create_worker(name="probe3", role="developer")
    assert res.get("status") == "created", res

    soul = (hermes_home / "profiles" / "probe3" / "SOUL.md").read_text()
    assert soul != "I am the operator.\n"


def test_custom_role_does_not_inherit_the_cloned_soul(tmp_path, monkeypatch):
    """A custom worker must not answer as the operator until its own SOUL lands.

    Core's ``--clone`` copies the source profile's SOUL.md, and a custom worker's
    SOUL.md is written afterwards by the caller — so the clone's copy has to go,
    or a caller that fails partway leaves a worker speaking with the user's voice.
    """
    from hermes_plugins.agora.agora import worker_manager

    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_KANBAN_DB", str(hermes_home / "kanban.db"))
    _stand_in_for_profile_create(monkeypatch)

    res = worker_manager.create_worker(name="probe4", role="custom")
    assert res.get("status") == "created", res

    assert not (hermes_home / "profiles" / "probe4" / "SOUL.md").exists()


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
def board_conn(tmp_path, board_connection):
    board = f"agora-hardening-{os.getpid()}-{tmp_path.name}"
    c = board_connection(board)
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


def test_capture_hermes_import_env_finds_the_core_tree_and_the_deps_dir(tmp_path, monkeypatch):
    """A spawned process needs *both* paths, not just an interpreter.

    Hermes' launcher puts the core tree on ``sys.path`` and ``hermes_bootstrap``
    -> ``pm.environments.activate_dependencies`` puts the selected environment's
    ``site-packages`` there. Neither reaches a child we spawn, so both have to
    be discoverable at generation time — and discovered, never guessed, so an
    install that keeps core outside ``$HERMES_HOME/hermes-agent`` still resolves.
    """
    core = tmp_path / "core"
    (core / "hermes_cli").mkdir(parents=True)
    (core / "hermes_cli" / "__init__.py").write_text("")
    deps = tmp_path / "site-packages"
    deps.mkdir()
    unrelated = tmp_path / "elsewhere"
    unrelated.mkdir()

    monkeypatch.setattr(sys, "path", [str(core), str(deps), str(unrelated)] + sys.path)
    core_roots, deps_dirs = utils.capture_hermes_import_env()

    assert str(core) in core_roots
    assert str(deps) in deps_dirs
    # A plain directory is neither: only the two defined shapes qualify.
    assert str(unrelated) not in core_roots
    assert str(unrelated) not in deps_dirs


def test_heartbeat_script_bakes_the_hermes_import_paths(tmp_path, monkeypatch):
    """The heartbeat runs under a tool Python that has neither path.

    ``sys.executable`` is Hermes' bundled tool Python, so the interpreter that
    generated the script is not sufficient on its own, and cron adds nothing.
    A board read that fails on every heartbeat makes the completion gate defer
    forever, which looks exactly like a project that is still working.
    """
    import subprocess

    # A quote and a dollar in the path, so the round-trip below only passes if
    # the value was shell-quoted: it lands unquoted in an assignment in the
    # generated script, where a bare `"` would be swallowed and a `$` expanded.
    core = tmp_path / 'core "quoted" $dollar'
    (core / "hermes_cli").mkdir(parents=True)
    (core / "hermes_cli" / "__init__.py").write_text("")
    deps = tmp_path / "site-packages"
    deps.mkdir()

    monkeypatch.setattr(sys, "path", [str(core), str(deps)] + sys.path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_HOME", raising=False)
    project_planner._ensure_heartbeat_script()

    body = (tmp_path / "scripts" / "leader_heartbeat.sh").read_text()
    assert "export PYTHONPATH=" in body
    # When the baked path stops resolving it must say so and stop, not run a
    # heartbeat that silently cannot read the board.
    assert "hermes_cli/__init__.py" in body
    assert "exit 1" in body

    # Let bash parse the assignments and hand the values back, rather than
    # matching the literal text.
    assignments = [
        line for line in body.splitlines()
        if line.startswith(("AGORA_CORE_ROOT=", "AGORA_DEPS_DIRS="))
    ]
    assert len(assignments) == 2, assignments
    check = subprocess.run(
        ["bash", "-c", "\n".join(
            assignments + ['printf "%s|%s" "$AGORA_CORE_ROOT" "$AGORA_DEPS_DIRS"']
        )],
        capture_output=True, text=True,
    )
    assert check.returncode == 0, check.stderr
    baked_core, baked_deps = check.stdout.split("|")
    assert baked_core == str(core)
    assert str(deps) in baked_deps.split(":")


def test_discussion_runner_env_carries_the_hermes_import_paths(tmp_path, monkeypatch):
    """The runner is spawned by a tool-Python interpreter with no path setup."""
    core = tmp_path / "core"
    (core / "hermes_cli").mkdir(parents=True)
    (core / "hermes_cli" / "__init__.py").write_text("")
    deps = tmp_path / "site-packages"
    deps.mkdir()

    monkeypatch.setattr(sys, "path", [str(core), str(deps)] + sys.path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)

    captured: dict = {}

    class _FakePopen:
        def __init__(self, *a, **k):
            self.pid = 1
            captured.update(k)

    monkeypatch.setattr(agent_spawn.subprocess, "Popen", _FakePopen)
    res = agent_spawn.spawn_discussion_driver(
        motion_id="m-paths", chair="leader", participants=["dev"],
        workdir=str(tmp_path), project_name="demo", max_steps=1,
    )
    assert res["status"] == "spawned"

    entries = captured["env"]["PYTHONPATH"].split(os.pathsep)
    assert entries[0] == str(core)
    assert str(deps) in entries
    # Carried in the environment, not by putting the plugin root on sys.path.
    assert "sys.path.insert" not in Path(res["runner"]).read_text()


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


def test_dashboard_plugin_api_works_without_package_context(tmp_path, monkeypatch):
    """The dashboard loader imports ``plugin_api.py`` as a top-level module.

    ``importlib.util.spec_from_file_location`` sets ``__package__`` to ``""``,
    so every relative import (``from ..agora.team_manager import …``) raises
    ``ImportError: attempted relative import with no known parent package`` and
    the endpoint returns 500. The shim at the top of ``plugin_api.py`` restores
    the package context; this test verifies it by loading the file exactly the
    way the dashboard does and calling an endpoint that uses a relative import.
    """
    import importlib.util as ilu

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)

    api_path = Path(__file__).resolve().parent.parent / "dashboard" / "plugin_api.py"
    spec = ilu.spec_from_file_location(
        "hermes_dashboard_plugin_agora", api_path,
    )
    assert spec is not None and spec.loader is not None
    mod = ilu.module_from_spec(spec)
    sys.modules["hermes_dashboard_plugin_agora"] = mod
    try:
        spec.loader.exec_module(mod)
    except ImportError:
        pytest.skip("FastAPI not importable in this environment")

    # list_teams calls `from ..agora.team_manager import list_teams` — the exact
    # relative import that returned 500 before the shim. It must not raise.
    result = mod.list_teams()
    assert "teams" in result

    # The shim must align the spec with __package__: Python 3.14+ emits
    # ``DeprecationWarning: __package__ != __spec__.parent`` on every relative
    # import otherwise, and that becomes an error on a later Python. The
    # spec's ``parent`` is read-only and derives from ``name``.
    assert mod.__spec__ is not None
    assert mod.__spec__.parent == mod.__package__, (
        "the spec still disagrees with __package__ — relative imports will warn "
        "on 3.14+ and fail on a later interpreter"
    )


# --------------------------------------------------------------------------- #
# Completion gate: every non-terminal work status must block PROJECT_COMPLETE  #
# --------------------------------------------------------------------------- #


def test_pending_statuses_exclude_the_parked_chat_root_status():
    """``scheduled`` must never count as pending work.

    Agora parks its per-project chat-root anchor task in ``scheduled`` forever
    (``agora/chat.py``). If the completion gate counted it, no project could
    ever complete — the anchor is always on the board.
    """
    from hermes_plugins.agora.agora.utils import PENDING_TASK_STATUSES

    assert "scheduled" not in PENDING_TASK_STATUSES


def test_pending_statuses_cover_every_non_terminal_work_status():
    """Every non-terminal status except the parked anchor must be counted.

    The gate used to query only ``running``/``ready``/``blocked``. Hermes'
    ``initial_task_state`` resolves a child task to ``todo`` when its parent is
    not ``done`` — which is the case for every motion, since motions hang off
    the (permanently ``scheduled``) chat root. So in-progress motions were
    invisible and a leader could declare the project complete mid-discussion.
    """
    from hermes_plugins.agora.agora.utils import PENDING_TASK_STATUSES

    terminal = {"done", "archived"}
    parked = {"scheduled"}  # the chat-root anchor
    expected = {"triage", "todo", "ready", "running", "blocked", "review"}

    assert expected <= set(PENDING_TASK_STATUSES), (
        "the completion gate would miss pending work in "
        f"{sorted(expected - set(PENDING_TASK_STATUSES))}"
    )
    assert not (terminal & set(PENDING_TASK_STATUSES))
    assert not (parked & set(PENDING_TASK_STATUSES))


def test_every_pending_status_has_a_summary_label():
    """The heartbeat summary renders a label per status — none may be missing.

    ``KeyError`` inside the summary builder is swallowed by its outer ``except``,
    which would silently drop the whole Kanban Summary section from AGENTS.md.
    """
    from hermes_plugins.agora.agora.utils import PENDING_TASK_STATUSES, STATUS_LABELS

    missing = [s for s in (*PENDING_TASK_STATUSES, "done") if s not in STATUS_LABELS]
    assert not missing, f"no summary label for {missing}"


def test_agents_md_summary_shows_todo_tasks(tmp_path, monkeypatch):
    """The leader's Kanban Summary must surface ``todo`` work.

    The summary listed only running/ready/review/blocked/done, so a motion —
    which lands in ``todo`` — was invisible to the leader reading AGENTS.md. The
    leader would then see a clean board and emit PROJECT_COMPLETE mid-discussion.
    """
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.setenv("HERMES_KANBAN_DB", str(tmp_path / "hermes-home" / "kanban.db"))
    workdir = tmp_path / "work"

    project_planner.start_project(
        project_name="summary-check", workdir=str(workdir), goal="dummy",
    )
    board = project_planner.agora_board_for("summary-check")

    conn = kb.connect()
    try:
        root = chat.ensure_chat_root(conn, project_name="summary-check", tenant=board)
        kb.create_task(
            conn, title="in-flight motion", tenant=board,
            initial_status="running", parents=[root],
        )
    finally:
        conn.close()

    project_planner.update_project_agents_md("summary-check")
    md = (workdir / "AGENTS.md").read_text()

    assert "## Kanban Summary" in md, "the summary section was dropped entirely"
    summary = md.split("## Kanban Summary", 1)[1].split("\n##", 1)[0]
    assert "Todo: 1" in summary, (
        f"in-flight todo work missing from the leader's board summary:\n{summary}"
    )


@pytest.fixture()
def completion_project(tmp_path, monkeypatch):
    """A registered, active project whose heartbeat log holds PROJECT_COMPLETE."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.setenv("HERMES_KANBAN_DB", str(tmp_path / "hermes-home" / "kanban.db"))

    name = f"gate-{tmp_path.name}"
    registry = project_planner.get_registry_dir("projects")
    (registry / f"{project_planner.safe_name(name)}.json").write_text(
        json.dumps({"name": name, "status": "active", "complete_check_pos": 0})
    )
    (registry / f"heartbeat_{project_planner.safe_name(name)}.log").write_text(
        "leader says PROJECT_COMPLETE\n"
    )
    return name


def test_check_project_complete_blocks_on_a_todo_task(completion_project):
    """The reported bug: a ``todo`` task must reject PROJECT_COMPLETE.

    ``todo`` is where Hermes puts motions and any child task whose parent is not
    done, so this is the status that actually carries in-flight work. Built the
    same way the plugin builds a motion: a child of the chat root, created with
    ``initial_status="running"``, which ``initial_task_state`` resolves to
    ``todo`` because the parent is not ``done``.
    """
    from hermes_plugins.agora.agora import chat, leader_loop

    board = project_planner.agora_board_for(completion_project)
    conn = kb.connect()
    try:
        root = chat.ensure_chat_root(conn, project_name=completion_project, tenant=board)
        child = kb.create_task(
            conn, title="post-deploy sign-off", tenant=board,
            initial_status="running", parents=[root],
        )
        status = conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (child,)
        ).fetchone()["status"]
    finally:
        conn.close()

    assert status == "todo", "a child of a non-done parent should resolve to todo"
    assert leader_loop.check_project_complete(completion_project) is False

    # ``False`` alone proves nothing: with the old (running/ready/blocked) query
    # the gate also returns False — it merely admits the FIRST of the two signals
    # it needs. What distinguishes a rejection is the counter: pending work keeps
    # it at 0, while a clean board increments it toward the stop.
    state = json.loads(
        (project_planner.get_registry_dir("projects")
         / f"{project_planner.safe_name(completion_project)}.json").read_text()
    )
    assert state.get("complete_count", 0) == 0, (
        "a todo task was not counted as pending work — the gate accepted the "
        "first PROJECT_COMPLETE signal while work was still on the board"
    )


def test_check_project_complete_fails_closed_when_the_board_is_unreadable(
    completion_project, monkeypatch,
):
    """A board read failure must not be mistaken for a clean board.

    ``check_project_complete`` treats "no pending tasks" as grounds to advance
    the stop counter. If the query raises — SQLite lock contention is routine —
    an empty result means "couldn't read", not "nothing there". Advancing anyway
    would stop the project with work still on the board, the same failure mode
    as querying too few statuses.
    """
    from hermes_plugins.agora.agora import kanban_compat, leader_loop

    class _UnreadableBoard:
        def connect(self, *args, **kwargs):
            raise RuntimeError("database is locked")

    monkeypatch.setattr(kanban_compat, "kanban_db", _UnreadableBoard())

    assert leader_loop.check_project_complete(completion_project) is False
    state = json.loads(
        (project_planner.get_registry_dir("projects")
         / f"{project_planner.safe_name(completion_project)}.json").read_text()
    )
    assert state.get("complete_count", 0) == 0, (
        "an unreadable board advanced the stop counter — a transient DB error "
        "could stop the project with work still pending"
    )


def test_check_project_complete_ignores_the_parked_chat_root(completion_project):
    """The chat root alone must not block completion.

    Regression guard for the naive fix: counting *all* non-terminal statuses
    would include the permanently-``scheduled`` anchor and pin every project at
    "not complete" forever.
    """
    from hermes_plugins.agora.agora import chat, leader_loop

    board = project_planner.agora_board_for(completion_project)
    conn = kb.connect()
    try:
        root = chat.ensure_chat_root(conn, project_name=completion_project, tenant=board)
        status = conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (root,)
        ).fetchone()["status"]
    finally:
        conn.close()

    assert status == "scheduled", "the chat root should be parked in scheduled"
    # No pending work — the gate must let the first signal through (counter
    # increments; the second consecutive signal is what stops the project).
    assert leader_loop.check_project_complete(completion_project) is False
    state = json.loads(
        (project_planner.get_registry_dir("projects")
         / f"{project_planner.safe_name(completion_project)}.json").read_text()
    )
    assert state.get("complete_count", 0) == 1, (
        "the parked chat root was counted as pending work — a project could "
        "never complete"
    )



# --------------------------------------------------------------------------- #
# Reported from a live install: heartbeat pileup (#6) and bad assignees (#4)   #
# --------------------------------------------------------------------------- #


@pytest.fixture()
def active_project(tmp_path, monkeypatch):
    """A registered, active project with a heartbeat member, no workers needed."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.setenv("HERMES_KANBAN_DB", str(tmp_path / "hermes-home" / "kanban.db"))

    name = f"live-{tmp_path.name}"
    project_planner.get_registry_dir("projects")
    (project_planner.get_registry_dir("projects")
     / f"{project_planner.safe_name(name)}.json").write_text(json.dumps({
        "name": name, "status": "active", "heartbeat_member": "leader",
        "complete_check_pos": 0, "last_heartbeat_at": None, "live_heartbeat_pids": [],
    }))
    return name


def test_live_heartbeat_pids_prunes_the_dead_and_keeps_the_living(active_project):
    """Only PIDs that are actually running count as in-flight (#6)."""
    name = active_project
    project_planner.update_heartbeat_status(name, pid=os.getpid())
    assert os.getpid() in project_planner.live_heartbeat_pids(name)

    # A PID that cannot be running (above the usual maximum) must be pruned,
    # not remembered: a stale entry would block every later heartbeat.
    project_planner.update_heartbeat_status(name, pid=999_999_999)
    live = project_planner.live_heartbeat_pids(name)
    assert os.getpid() in live
    assert 999_999_999 not in live


def test_heartbeat_skips_while_a_leader_is_in_flight(active_project):
    """A cron fire must not stack a second leader on a running one (#6).

    A heartbeat can outrun its own interval under model contention, so the gate
    has to consult liveness rather than assume the previous fire finished. The
    script-level flock does not help: it only covers the Popen call, which
    returns immediately while the leader keeps running detached.
    """
    from hermes_plugins.agora.agora import leader_loop

    name = active_project
    project_planner.update_heartbeat_status(name, pid=os.getpid())

    result = leader_loop.heartbeat(project=name)
    assert result.get("status") == "skipped_in_flight", (
        f"heartbeat spawned on top of a live leader: {result}"
    )
    assert os.getpid() in result.get("pids", [])


def test_heartbeat_spawns_once_the_leader_exits(active_project, monkeypatch):
    """The gate must open again — a stale PID would stall the project forever."""
    from hermes_plugins.agora.agora import leader_loop

    name = active_project
    project_planner.update_heartbeat_status(name, pid=999_999_999)  # never alive

    spawned: dict = {}
    monkeypatch.setattr(
        leader_loop, "_spawn_leader_agent",
        lambda proj: spawned.update(proj) or {"status": "spawned"},
    )
    result = leader_loop.heartbeat(project=name)
    assert result.get("status") == "spawned", f"gate stayed shut: {result}"


def test_reactivation_rebuilds_the_chat_channel(tmp_path, monkeypatch):
    """Stopping deletes the chat root; reactivating must mint a live one (#8).

    ``stop_project`` deletes every kanban task the project owns, chat root
    included, so the persisted ``chat_root_id`` becomes a dead id. The
    reactivation branch re-created the heartbeat cron but not the channel, so
    every later ``agora_raise_motion`` failed with "unknown parent task(s)" and
    the leader re-probed a dead channel until the project parked itself.
    """
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.setenv("HERMES_KANBAN_DB", str(tmp_path / "hermes-home" / "kanban.db"))
    workdir = tmp_path / "work"

    first = project_planner.start_project(
        project_name="re-up", workdir=str(workdir), goal="dummy",
    )
    first_root = first["project"].get("chat_root_id")
    assert first_root, "a fresh project must get a chat channel"

    # Stop: deletes every task on the project's board, chat root included.
    project_planner.stop_project("re-up")
    conn = kb.connect()
    try:
        alive = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE id = ?", (first_root,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert alive == 0, "the stopped chat root should be gone"

    # Re-activate the same project — this is the branch that skipped the channel.
    reactivated = project_planner.start_project(
        project_name="re-up", workdir=str(workdir), goal="dummy again",
    )
    assert reactivated.get("status") == "started", reactivated
    project = reactivated["project"]
    assert project["status"] == "active"
    new_root = project.get("chat_root_id")
    assert new_root and new_root != first_root, "reactivation reused the dead id"

    # The id has to survive the branch's own write of the project file.
    on_disk = json.loads(project_planner._project_file("re-up").read_text())
    assert on_disk["chat_root_id"] == new_root, "the write clobbered the fresh id"

    # And it must be a task that actually exists, so motions can parent to it.
    conn = kb.connect()
    try:
        exists = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE id = ?", (new_root,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert exists == 1, "the reactivated chat root is not a live task"


def test_update_project_reactivate_rebuilds_the_chat_channel(tmp_path, monkeypatch):
    """``update_project(reactivate=True)`` goes through the same branch (#8).

    Same failure, second entry point: the flag re-creates the heartbeat cron
    and stops there.
    """
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.setenv("HERMES_KANBAN_DB", str(tmp_path / "hermes-home" / "kanban.db"))
    workdir = tmp_path / "work"

    first = project_planner.start_project(
        project_name="re-up2", workdir=str(workdir), goal="dummy",
    )
    first_root = first["project"].get("chat_root_id")
    project_planner.stop_project("re-up2")

    updated = project_planner.update_project("re-up2", reactivate=True, goal="phase 2")
    assert updated.get("status") == "updated", updated
    project = updated["project"]
    assert project["status"] == "active"
    new_root = project.get("chat_root_id")
    assert new_root and new_root != first_root

    on_disk = json.loads(project_planner._project_file("re-up2").read_text())
    assert on_disk["chat_root_id"] == new_root, "the write clobbered the fresh id"
    assert on_disk["goal"] == "phase 2", "the reactivate dropped the other changes"

    conn = kb.connect()
    try:
        exists = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE id = ?", (new_root,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert exists == 1, "the reactivated chat root is not a live task"


def test_update_project_without_reactivate_still_persists(tmp_path, monkeypatch):
    """A plain update must still write the file (guard against over-indenting)."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    workdir = tmp_path / "work"

    project_planner.start_project(
        project_name="plain-up", workdir=str(workdir), goal="dummy",
    )
    updated = project_planner.update_project("plain-up", goal="changed")
    assert updated.get("status") == "updated", updated
    assert updated["project"]["goal"] == "changed"

    on_disk = json.loads(project_planner._project_file("plain-up").read_text())
    assert on_disk["goal"] == "changed", "a plain update did not reach disk"


def test_reactivation_leaves_the_chat_root_usable_by_a_motion(tmp_path, monkeypatch):
    """The end-to-end consequence: a motion can hang off the reactivated root."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    workdir = tmp_path / "work"

    project_planner.start_project(
        project_name="re-motion", workdir=str(workdir), goal="dummy",
    )
    project_planner.stop_project("re-motion")
    reactivated = project_planner.start_project(
        project_name="re-motion", workdir=str(workdir), goal="dummy",
    )
    root = reactivated["project"]["chat_root_id"]

    conn = kb.connect()
    try:
        motion_id = motion_mod.create_motion(
            conn, chat_root_id=root, title="after reactivation",
            participants=["a", "b"], chair="leader",
            tenant=project_planner.agora_board_for("re-motion"),
        )
    finally:
        conn.close()
    assert motion_id, "a motion could not be created on the reactivated root"


def _stand_in_for_profile_create(monkeypatch) -> list:
    """Provision worker profiles without shelling out to the ``hermes`` CLI.

    ``create_worker`` delegates to ``hermes profile create --clone`` so the plugin
    never reads the user's ``.env`` itself (catalog rule 11). A test has no
    configured Hermes home for that CLI to clone from, so this stands in for it:
    create the profile directory and the files core would have copied. Returns the
    recorded commands, so a test can assert on the delegation.
    """
    from hermes_plugins.agora.agora import worker_manager

    profiles_root = worker_manager.get_profiles_root()
    calls: list = []

    class _Done:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, "env": kwargs.get("env") or {}})
        name = cmd[cmd.index("create") + 1]
        profile = profiles_root / name
        profile.mkdir(parents=True, exist_ok=True)
        (profile / "config.yaml").write_text("model:\n  default: probe\n")
        (profile / ".env").write_text("PROBE=1\n")
        # Core's --clone brings the source profile's SOUL.md along too.
        (profile / "SOUL.md").write_text("I am the operator.\n")
        return _Done()

    monkeypatch.setattr(worker_manager.subprocess, "run", _fake_run)
    monkeypatch.setattr(worker_manager, "find_hermes_binary", lambda: "hermes")
    return calls


@pytest.fixture()
def team_project(tmp_path, monkeypatch):
    """An active project bound to a team with one developer and one reviewer."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.setenv("HERMES_KANBAN_DB", str(tmp_path / "hermes-home" / "kanban.db"))
    _stand_in_for_profile_create(monkeypatch)

    from hermes_plugins.agora.agora import team_manager, worker_manager

    workdir = tmp_path / "work"
    project_planner.start_project(
        project_name="assignees", workdir=str(workdir), goal="dummy",
    )
    for worker, role in (("dev-alpha", "developer"), ("rev-alpha", "reviewer")):
        worker_manager.create_worker(name=worker, role=role)
    team_manager.create_team("accept-team", ["dev-alpha", "rev-alpha"], project="assignees")
    return "assignees"


def _create_task_handler():
    from hermes_plugins.agora import tools as tools_mod

    registered: dict = {}

    class _Ctx:
        def register_tool(self, **kwargs):
            registered[kwargs["name"]] = kwargs

        def register_command(self, *args, **kwargs):
            pass

    tools_mod.register_all_tools(_Ctx())
    return registered["agora_create_task"]["handler"]


def _call_tool(handler, args):
    """Handlers may be sync or async; the tool contract allows both."""
    import asyncio
    import inspect

    result = handler(args)
    return asyncio.run(result) if inspect.isawaitable(result) else result


def test_create_task_rejects_an_unknown_assignee(team_project):
    """A role that isn't on the team must be refused, with the valid roles (#4).

    The assignee was written to the task verbatim, so the dispatcher tried to
    spawn a profile that does not exist: the worker crashed, re-spawned, and the
    task stayed ``running`` forever.
    """
    handler = _create_task_handler()
    result = _call_tool(handler, {"title": "t", "assignee": "mlops", "project": team_project})

    payload = json.loads(result) if isinstance(result, str) else result
    assert "error" in payload, f"an unknown role was accepted: {result}"
    assert "mlops" in payload["error"]
    assert "developer" in payload.get("hint", ""), "the error must list the valid roles"


def test_create_task_accepts_a_real_role_and_a_real_worker(team_project):
    """The gate must not reject anything legitimate."""
    handler = _create_task_handler()

    by_role = _call_tool(handler, {"title": "t", "assignee": "developer", "project": team_project})
    by_role = json.loads(by_role) if isinstance(by_role, str) else by_role
    assert by_role.get("assignee") == "dev-alpha", "the role should resolve to its worker"

    by_name = _call_tool(handler, {"title": "t", "assignee": "rev-alpha", "project": team_project})
    by_name = json.loads(by_name) if isinstance(by_name, str) else by_name
    assert by_name.get("assignee") == "rev-alpha"

    unassigned = _call_tool(handler, {"title": "t", "project": team_project})
    unassigned = json.loads(unassigned) if isinstance(unassigned, str) else unassigned
    assert "error" not in unassigned, "an omitted assignee is not an invalid one"


def test_heartbeat_gate_reopens_for_a_recycled_pid(active_project, monkeypatch):
    """A recycled PID must not pin the gate shut (#6 follow-up).

    Liveness alone is not enough: the OS reuses PIDs, so an unrelated
    long-lived process can inherit the leader's PID and make ``os.kill(pid, 0)``
    succeed forever — leaving the project with no leader at all, which is worse
    than the pileup the gate exists to prevent.

    This uses the bare-int shape v2.0.10 wrote, precisely because it carries no
    age: an entry whose age cannot be checked can never expire, so it must be
    dropped rather than trusted.
    """
    from hermes_plugins.agora.agora import leader_loop

    name = active_project
    project_file = (
        project_planner.get_registry_dir("projects")
        / f"{project_planner.safe_name(name)}.json"
    )
    state = json.loads(project_file.read_text())

    # PID 1 is always alive — stand in for a recycled PID a dead leader left.
    state["live_heartbeat_pids"] = [1]
    project_file.write_text(json.dumps(state))

    assert project_planner.live_heartbeat_pids(name) == [], (
        "an entry with no checkable age still counts as in-flight — a recycled "
        "PID would block every future heartbeat"
    )

    spawned: dict = {}
    monkeypatch.setattr(
        leader_loop, "_spawn_leader_agent",
        lambda proj: spawned.update(proj) or {"status": "spawned"},
    )
    result = leader_loop.heartbeat(project=name)
    assert result.get("status") == "spawned", f"gate stayed shut: {result}"


def test_heartbeat_gate_reopens_for_an_aged_out_entry(active_project, monkeypatch):
    """A timestamped entry older than the ceiling must release the gate.

    This is the recycled-PID case for entries that *do* carry an age: the PID is
    still alive (some unrelated process has it), but the leader that owned it is
    long gone, so the entry must stop counting.
    """
    import time

    from hermes_plugins.agora.agora import leader_loop

    name = active_project
    project_file = (
        project_planner.get_registry_dir("projects")
        / f"{project_planner.safe_name(name)}.json"
    )
    state = json.loads(project_file.read_text())
    state["live_heartbeat_pids"] = [
        {"pid": 1, "at": time.time() - 3 * 3600},
    ]
    project_file.write_text(json.dumps(state))

    assert project_planner.live_heartbeat_pids(name) == [], (
        "an entry past the maximum runtime still counts as in-flight"
    )
    monkeypatch.setattr(
        leader_loop, "_spawn_leader_agent",
        lambda proj: {"status": "spawned"},
    )
    assert leader_loop.heartbeat(project=name).get("status") == "spawned"


def test_heartbeat_gate_keeps_a_fresh_live_entry(active_project):
    """The ceiling must not defeat the gate for a genuinely running leader."""
    import time as _time

    name = active_project
    project_file = (
        project_planner.get_registry_dir("projects")
        / f"{project_planner.safe_name(name)}.json"
    )
    state = json.loads(project_file.read_text())
    state["live_heartbeat_pids"] = [{"pid": os.getpid(), "at": _time.time()}]
    project_file.write_text(json.dumps(state))

    assert os.getpid() in project_planner.live_heartbeat_pids(name)


def test_heartbeat_pids_drop_the_legacy_bare_int_shape(active_project):
    """v2.0.10 briefly stored bare ints; those must be dropped, not trusted.

    They carry no age, and an age we cannot check can never expire. Trusting
    them would let a recycled PID pin the gate forever. Dropping them costs at
    most one redundant leader on the first heartbeat after upgrading.
    """
    name = active_project
    project_file = (
        project_planner.get_registry_dir("projects")
        / f"{project_planner.safe_name(name)}.json"
    )
    state = json.loads(project_file.read_text())
    state["live_heartbeat_pids"] = [os.getpid()]  # alive, but ageless
    project_file.write_text(json.dumps(state))

    assert project_planner.live_heartbeat_pids(name) == []


def test_heartbeat_pids_round_trip_a_fresh_entry(active_project):
    """A PID recorded now must survive a read, and be stored with its age."""
    name = active_project
    project_planner.update_heartbeat_status(name, pid=os.getpid())

    assert os.getpid() in project_planner.live_heartbeat_pids(name)
    stored = json.loads(
        (project_planner.get_registry_dir("projects")
         / f"{project_planner.safe_name(name)}.json").read_text()
    )["live_heartbeat_pids"]
    assert stored == [{"pid": os.getpid(), "at": stored[0]["at"]}], stored
    assert isinstance(stored[0]["at"], float), "the entry must record its age"


# --------------------------------------------------------------------------- #
# Worker provisioning, second half: undo what the clone copies                  #
#                                                                             #
# `--no-skills` cannot accompany any clone option, so the clone brings the      #
# source profile's whole skills tree (43 entries on a stock install) and it has  #
# to be undone afterwards — empty skills/ plus core's opt-out marker, which is  #
# the state `--no-skills` would have produced.                                  #
# --------------------------------------------------------------------------- #

def test_profile_create_command_never_pairs_no_skills_with_a_clone():
    from hermes_plugins.agora.agora import worker_manager as wm

    cmd = wm._profile_create_command("hermes", "dev", "desc", None)

    assert "--no-skills" not in cmd
    assert "--clone" not in cmd, "--clone-from already implies the clone"
    assert "--clone-from" in cmd
    assert cmd[cmd.index("--clone-from") + 1] == "default"


def test_profile_create_command_honours_an_explicit_source():
    from hermes_plugins.agora.agora import worker_manager as wm

    cmd = wm._profile_create_command("hermes", "dev", "desc", "research")

    assert cmd[cmd.index("--clone-from") + 1] == "research"
    assert "--no-skills" not in cmd


def test_drop_cloned_skills_empties_the_tree_and_writes_the_marker(tmp_path):
    from hermes_plugins.agora.agora import worker_manager as wm

    skills = tmp_path / "skills"
    (skills / "one").mkdir(parents=True)
    (skills / "one" / "SKILL.md").write_text("x")
    (skills / "two").mkdir()
    (skills / "loose.md").write_text("y")

    wm._drop_cloned_skills(tmp_path)

    assert sorted(child.name for child in skills.iterdir()) == []
    marker = tmp_path / wm.NO_BUNDLED_SKILLS_MARKER
    assert marker.is_file()
    assert "opted out of bundled-skill seeding" in marker.read_text()


def test_drop_cloned_skills_tolerates_a_missing_skills_dir(tmp_path):
    from hermes_plugins.agora.agora import worker_manager as wm

    wm._drop_cloned_skills(tmp_path)

    assert (tmp_path / wm.NO_BUNDLED_SKILLS_MARKER).is_file()


def test_no_source_line_pairs_no_skills_with_a_clone():
    """Invariant for the whole class: core raises on that combination, so any
    call site rebuilding it breaks worker creation again."""
    root = Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if "__pycache__" in rel.parts or rel.parts[0] == "tests":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if '"--no-skills"' in code and '"--clone' in code:
                offenders.append(f"{rel}:{lineno}")
    assert offenders == [], (
        "--no-skills is mutually exclusive with --clone/--clone-from/--clone-all; "
        f"core raises on the pair: {offenders}"
    )
