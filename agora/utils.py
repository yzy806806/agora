"""Shared utilities for Agora modules.

Centralizes path resolution, binary discovery, and common helpers
used across worker_manager, leader_manager, team_manager, leader_loop,
and project_planner.
"""
from __future__ import annotations

import json
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
        "/usr/local/lib/hermes-agent/venv/bin/hermes",
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
    """Patch the model field in a profile's config.yaml.

    Handles both formats:
    - New (dict): ``model:\\n  default: <name>``
    - Old (flat string): ``model: <name>``

    If the old flat format is found, it is upgraded to the new dict format
    so Hermes can resolve the provider and base_url from custom_providers.

    Uses structured yaml.safe_load/safe_dump — not regex — so comments,
    anchors, and non-model fields are preserved.
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        if cfg is None:
            cfg = {}
        if not isinstance(cfg, dict):
            logger.warning("patch_config_model: config at %s is not a dict, skipping", config_path)
            return

        model_cfg = cfg.get("model")
        if isinstance(model_cfg, dict):
            # New dict format — just update the default
            if model_cfg.get("default") != model:
                model_cfg["default"] = model
                cfg["model"] = model_cfg
                with open(config_path, "w") as f:
                    yaml.safe_dump(cfg, f, default_flow_style=False, allow_unicode=True)
                logger.info("patch_config_model: set model.default=%s (dict format)", model)
            return

        # Old flat format or missing — upgrade to dict format
        cfg["model"] = {"default": model}
        with open(config_path, "w") as f:
            yaml.safe_dump(cfg, f, default_flow_style=False, allow_unicode=True)
        logger.info("patch_config_model: upgraded model from flat to dict format, default=%s", model)
    except Exception as exc:
        logger.warning("patch_config_model failed for %s: %s", config_path, exc)


def ensure_in_place_compression(config_path: Path) -> None:
    """Ensure a profile's config.yaml has compression.in_place: true.

    When Hermes compresses conversation context, ``in_place: true`` ensures
    the session ID does NOT change — so ``--resume <session_id>`` always
    works for worker/leader agents that are spawned repeatedly.

    This function:
      - Reads the config.yaml at ``config_path``
      - Creates a ``compression`` section if it doesn't exist
      - Sets ``compression.in_place: true`` if not already set
      - Writes back only if a change was made
      - Uses yaml.safe_load / yaml.safe_dump
      - Swallows errors with a warning log (never crashes the caller)
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        import yaml
        if not config_path.exists():
            logger.debug("ensure_in_place_compression: config not found at %s", config_path)
            return

        with open(config_path) as f:
            config = yaml.safe_load(f)
        if config is None:
            config = {}
        if not isinstance(config, dict):
            logger.warning("ensure_in_place_compression: config at %s is not a dict, skipping", config_path)
            return

        compression = config.get("compression")
        if compression is None:
            compression = {}
        if not isinstance(compression, dict):
            logger.warning("ensure_in_place_compression: compression section is not a dict, skipping")
            return

        changed = False
        if "in_place" not in compression:
            compression["in_place"] = True
            changed = True
        elif compression["in_place"] is not True:
            compression["in_place"] = True
            changed = True

        if changed:
            config["compression"] = compression
            with open(config_path, "w") as f:
                yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)
            logger.info("Set compression.in_place=true in %s", config_path)
    except Exception as exc:
        logger.warning("ensure_in_place_compression failed for %s: %s", config_path, exc)


def safe_name(name: str) -> str:
    """Sanitize a name for use as a filename."""
    import re
    # Replace path separators and whitespace first
    name = name.replace("/", "-").replace(" ", "_")
    # Strip any remaining characters that are unsafe in filenames
    name = re.sub(r'[<>:"|?*\\;{}()\[\]$~`!@#%^&=+]', "", name)
    return name


def parse_json_response(text: str) -> dict | None:
    """Extract and parse a JSON object from an LLM response string.

    Handles common LLM output quirks:
      - Strips markdown code fences (```json ... ```)
      - Finds the first ``{...}`` block via regex (DOTALL)
      - Returns ``None`` if the text is not valid JSON

    Extracted from ``agora/discussion/driver.py::_parse_json`` so all
    callers share one robust implementation.
    """
    import re

    text = text.strip()

    # Strip markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        text = "\n".join(lines)

    # Try to find JSON object in the text
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        text = match.group(0)

    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
