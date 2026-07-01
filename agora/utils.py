"""Shared utilities for Agora modules.

Centralizes path resolution, binary discovery, and common helpers
used across worker_manager, leader_manager, team_manager, leader_loop,
and project_planner.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def get_global_root() -> Path:
    """Return the global Hermes home directory (not profile-scoped).

    All Agora registries (workers, leaders, teams, projects) live under
    this path so they're shared across all profiles.
    """
    kanban_db = os.environ.get("HERMES_KANBAN_DB", "")
    if kanban_db:
        return Path(kanban_db).parent
    try:
        from hermes_constants import get_hermes_home
        home = Path(get_hermes_home())
        if "/profiles/" in str(home):
            return home.parent.parent
        return home
    except Exception:
        return Path.home() / ".hermes"


def get_registry_dir(name: str) -> Path:
    """Return (and create) a registry subdirectory under agora/."""
    d = get_global_root() / "agora" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_profiles_root() -> Path:
    """Return the path to ~/.hermes/profiles/."""
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


def find_hermes_binary() -> str:
    """Find the hermes executable."""
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
    return shutil.which("hermes") or "hermes"


def now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def patch_config_model(config_path: Path, model: str) -> None:
    """Patch the model.default field in a profile's config.yaml."""
    import re
    try:
        content = config_path.read_text()
        new_content = re.sub(
            r'(\nmodel:\n  default: )([^\n]+)',
            f'\\g<1>{model}',
            content, count=1,
        )
        if new_content != content:
            config_path.write_text(new_content)
    except Exception:
        pass


def safe_name(name: str) -> str:
    """Sanitize a name for use as a filename."""
    return name.replace("/", "-").replace(" ", "_")
