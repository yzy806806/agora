"""Pytest configuration and shared fixtures for Agora tests."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import os
import types
from pathlib import Path

import pytest

# Load the plugin the way Hermes does — as ``hermes_plugins.agora`` with its own
# search path, executing ``__init__.py`` — so the package's relative imports AND
# its package-level symbols resolve exactly as they do at runtime. Two things
# this used to get wrong:
#
#   * putting the plugin root on sys.path (as this file first did) shadows core's
#     own ``tools`` package and leaves the cross-package relative imports
#     unresolvable;
#   * registering a bare module without executing ``__init__.py`` hides anything
#     defined there, which is how a ``from . import deploy_bundled_skills`` that
#     pointed at the wrong package slipped through.
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PKG = "hermes_plugins.agora"


def _patch_editable_finder():
    """Patch the editable-install finder's MAPPING in memory if Hermes added new top-level modules.

    When Hermes updates, it sometimes adds new top-level ``.py`` files (e.g.
    ``hermes_state_pidns.py``, ``hermes_state_coverage.py``) without regenerating
    the editable-install ``__editable___hermes_agent_*_finder.py`` MAPPING that
    maps module names to their source paths.  Any lazy import of those modules
    then fails with ``ModuleNotFoundError`` — not because the code is wrong, but
    because the finder doesn't know the module exists.

    This function scans the Hermes installation root for top-level modules/packages
    that are absent from the finder's MAPPING and patches the in-memory dict
    (if the finder is already imported) so the fix takes effect immediately in
    the current process.  It does NOT write to the finder file on disk — the
    stale file is an upstream issue, and writing to it from a test suite has
    side effects on the host install.  When the finder is stale the in-memory
    patch is sufficient; when it isn't imported yet the tests simply skip the
    affected modules.  No-op when the finder is already up to date.
    """
    import re

    # Locate the Hermes installation root.
    hermes_root = None
    for entry in sys.path:
        if entry == "/usr/local/lib/hermes-agent":
            hermes_root = Path(entry)
            break
    if hermes_root is None:
        try:
            import hermes_constants
            hermes_root = Path(hermes_constants.__file__).resolve().parent
        except Exception:
            return

    # Find the editable finder on disk to read its MAPPING (without writing).
    venv_site = hermes_root / "venv/lib"
    candidates = list(venv_site.glob("**/__editable___hermes_agent_*_finder.py"))
    if not candidates:
        return
    finder_path = candidates[0]
    src = finder_path.read_text()

    m = re.search(r"MAPPING\s*(?::\s*dict\[str,\s*str\])?\s*=\s*\{([^}]*)\}", src, re.S)
    if not m:
        return
    mapping_body = m.group(1)
    registered = set(re.findall(r"'([A-Za-z_][A-Za-z0-9_]*)':", mapping_body))

    mods = {p.stem for p in hermes_root.glob("*.py") if p.name != "setup.py"}
    pkgs = {
        d.name for d in hermes_root.iterdir()
        if d.is_dir() and (d / "__init__.py").exists()
        and d.name not in {"venv", "node_modules", ".git", "__pycache__", "evals", "docs", "tests"}
    }
    missing = sorted((mods | pkgs) - registered)
    if not missing:
        return

    # Patch the in-memory MAPPING dict so the current process is fixed.
    # The finder module may already be imported; walk sys.modules to find it.
    for mod_name, mod_obj in list(sys.modules.items()):
        mapping = getattr(mod_obj, "MAPPING", None)
        if isinstance(mapping, dict):
            for mod in missing:
                mapping[mod] = str(hermes_root / mod)
            break


try:
    _patch_editable_finder()
except Exception:
    pass  # not worth failing the test session over


if PKG not in sys.modules:
    if "hermes_plugins" not in sys.modules:
        _ns = types.ModuleType("hermes_plugins")
        _ns.__path__ = []
        sys.modules["hermes_plugins"] = _ns
    _spec = importlib.util.spec_from_file_location(
        PKG, _PLUGIN_ROOT / "__init__.py",
        submodule_search_locations=[str(_PLUGIN_ROOT)],
    )
    assert _spec is not None and _spec.loader is not None, "cannot load the plugin package"
    _pkg = importlib.util.module_from_spec(_spec)
    _pkg.__package__ = PKG
    _pkg.__path__ = [str(_PLUGIN_ROOT)]
    sys.modules[PKG] = _pkg
    _spec.loader.exec_module(_pkg)


@pytest.fixture(autouse=True)
def _hermetic_kanban_db(tmp_path, monkeypatch):
    """Pin the kanban DB inside the test's tmp dir.

    The board fixtures call ``kanban_db.connect(board=...)``, which resolves its
    path from ``HERMES_KANBAN_DB`` / the Hermes home. Without this the suite
    depends on the ambient environment being writable and pre-created — on a
    machine where it is not, every board fixture errors with "unable to open
    database file" and the failures look like real ones. Isolating per test also
    means a test can never touch a real board.
    """
    monkeypatch.setenv("HERMES_KANBAN_DB", str(tmp_path / "kanban.db"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    return tmp_path / "kanban.db"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Monkeypatch motions._agora_db_path to return a path in a temp directory.

    This ensures tests never touch the real ~/.hermes/agora/motions.db.
    """
    from hermes_plugins.agora.agora.storage import motions

    db_path = tmp_path / "motions.db"
    monkeypatch.setattr(motions, "_agora_db_path", lambda: db_path)
    return db_path


@pytest.fixture()
def clean_db(temp_db):
    """Create a fresh DB for each test by ensuring the schema is initialised."""
    from hermes_plugins.agora.agora.storage import motions

    # _connect() calls _init_schema() which creates tables if they don't exist.
    conn = motions._connect()
    conn.close()
    yield temp_db
