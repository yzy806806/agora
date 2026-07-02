"""Worker profile manager — create, list, remove Hermes profiles from templates.

A "worker" is a Hermes profile with:
  - config.yaml    (cloned from a parent profile, e.g. coder)
  - SOUL.md        (role identity, rendered from template)
  - MEMORY.md      (empty initially, accumulates experience over time)
  - USER.md        (empty initially)
  - skills/        (profile-local skills directory, independent from global)
  - description    (set via `hermes profile describe`)

Workers persist across projects. Their memory, skills, and identity are
personal — they carry experience from one project to the next, just like
a real employee.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .utils import (
    get_registry_dir,
    get_profiles_root,
    find_hermes_binary,
    now_iso,
    patch_config_model,
    safe_name,
    ensure_in_place_compression,
)
from .worker_templates import TEMPLATES, get_template, render_soul, list_templates

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  Registry — tracks which profiles are Agora-managed workers                 #
# --------------------------------------------------------------------------- #

def _worker_file(name: str) -> Path:
    return get_registry_dir("workers") / f"{safe_name(name)}.json"


# --------------------------------------------------------------------------- #
#  Public API                                                                 #
# --------------------------------------------------------------------------- #

def create_worker(
    name: str,
    role: str,
    clone_from: str = "coder",
    model: str | None = None,
    extra_config: dict | None = None,
) -> dict:
    """Create a new worker profile from a role template.

    This creates a full Hermes profile with:
    - Cloned config.yaml (API keys, model, toolsets) from clone_from
    - SOUL.md rendered from the role template
    - Empty MEMORY.md and USER.md
    - Independent skills/ directory
    - Profile description set for kanban routing

    Args:
        name:        Profile name (lowercase, alphanumeric, e.g. "alice")
        role:        Template role key (architect/developer/reviewer/tester/devops)
        clone_from:  Source profile to clone config from (default: coder)
        model:       Override model for this worker (default: from template or inherit)
        extra_config: Additional config overrides (rarely needed)

    Returns:
        dict with creation status and worker info
    """
    # Validate name
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        return {"error": f"Invalid worker name '{name}'. Use lowercase alphanumeric with - or _."}

    # Check if already exists
    if _worker_file(name).exists():
        return {"error": f"Worker '{name}' already exists. Remove it first or use a different name."}

    # Handle custom role — no template, SOUL.md written separately by caller
    if role == "custom":
        template = None
        display_name = "Custom"
        description = "Custom worker with LLM-generated SOUL.md"
    else:
        template = get_template(role)
        if template is None:
            available = ", ".join(TEMPLATES.keys())
            return {"error": f"Unknown role '{role}'. Available: {available}"}
        display_name = template["display_name"]
        description = template["description"]

    profiles_root = get_profiles_root()
    profile_dir = profiles_root / name

    # Check if profile dir already exists (maybe created manually)
    if profile_dir.exists():
        return {"error": f"Profile directory '{profile_dir}' already exists."}

    # Step 1: Clone the profile using hermes CLI
    hermes = find_hermes_binary()
    clone_cmd = [
        hermes, "profile", "create", name,
        "--clone-from", clone_from,
        "--description", description,
    ]
    try:
        result = subprocess.run(
            clone_cmd,
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "HERMES_HOME": str(profiles_root.parent)},
        )
        if result.returncode != 0:
            return {
                "error": f"Failed to clone profile: {result.stderr.strip() or result.stdout.strip()}",
                "command": " ".join(clone_cmd),
            }
    except Exception as exc:
        return {"error": f"Failed to clone profile: {exc}"}

    # Step 1b: Ensure config.yaml exists in the profile directory.
    # Profiles without config.yaml fall back to DEFAULT_CONFIG (compression
    # threshold=0.50, target_ratio=0.20 — too aggressive). Copy from root
    # config so the profile inherits the user's actual settings.
    profile_config = profile_dir / "config.yaml"
    if not profile_config.exists():
        try:
            root_config = profiles_root.parent / "config.yaml"
            if root_config.exists():
                shutil.copy2(root_config, profile_config)
        except Exception as exc:
            logger.warning("Failed to copy config.yaml to profile %s: %s", name, exc)

    # Step 1c: Ensure compression.in_place: true so session IDs don't change
    # on context compression — --resume <session_id> always works.
    ensure_in_place_compression(profile_dir / "config.yaml")

    # Step 2: Write SOUL.md
    if template is not None:
        soul_path = profile_dir / "SOUL.md"
        soul_content = render_soul(template, name)
        try:
            soul_path.write_text(soul_content)
        except Exception as exc:
            logger.warning("Failed to write SOUL.md for %s: %s", name, exc)
    # For custom role, SOUL.md is written separately by the caller

    # Step 3: Ensure MEMORY.md exists (empty, not cloned from parent)
    memory_path = profile_dir / "MEMORY.md"
    try:
        if not memory_path.exists() or memory_path.stat().st_size == 0:
            memory_path.write_text(f"# {name} Memory\n\nPersonal experience and learned facts.\n")
        else:
            # Overwrite with clean personal memory (don't inherit parent's)
            memory_path.write_text(f"# {name} Memory\n\nPersonal experience and learned facts.\n")
    except Exception as exc:
        logger.warning("Failed to write MEMORY.md for %s: %s", name, exc)

    # Step 4: Ensure USER.md exists
    user_path = profile_dir / "USER.md"
    try:
        user_path.write_text(f"# {name}\n\nRole: {display_name}\n")
    except Exception as exc:
        logger.warning("Failed to write USER.md for %s: %s", name, exc)

    # Step 5: Ensure skills/ dir exists (profile-local, independent)
    skills_dir = profile_dir / "skills"
    try:
        skills_dir.mkdir(parents=True, exist_ok=True)
        # Create a .gitkeep so the dir isn't empty
        (skills_dir / ".gitkeep").touch()
    except Exception as exc:
        logger.warning("Failed to create skills dir for %s: %s", name, exc)

    # Step 6: Override model if specified or from template
    effective_model = model or (template.get("model") if template else None)
    if effective_model:
        patch_config_model(profile_dir / "config.yaml", effective_model)

    # Step 7: Register in the worker registry
    worker_data = {
        "name": name,
        "role": role,
        "display_name": display_name,
        "description": description,
        "clone_from": clone_from,
        "model": effective_model or "inherited",
        "profile_dir": str(profile_dir),
        "created_at": now_iso(),
        "projects": [],  # list of project names this worker participates in
        "session_id": None,  # filled after first agent spawn, for --resume
    }
    _worker_file(name).write_text(json.dumps(worker_data, indent=2))

    logger.info(
        "Worker '%s' created (role=%s, model=%s, dir=%s)",
        name, role, effective_model or "inherited", profile_dir,
    )

    return {"status": "created", "worker": worker_data}


def remove_worker(name: str, delete_profile: bool = True) -> dict:
    """Remove a worker from the Agora registry.

    Args:
        name:           Worker profile name
        delete_profile: If True, also delete the Hermes profile directory.
                        If False, only unregister from Agora.

    Returns:
        dict with removal status
    """
    wf = _worker_file(name)
    if not wf.exists():
        return {"error": f"Worker '{name}' not found in Agora registry"}

    data = json.loads(wf.read_text())

    # Check if worker is in any active project
    if data.get("projects"):
        return {
            "error": f"Worker '{name}' is in active projects: {data['projects']}. "
                     f"Remove from teams first.",
        }

    # Delete the Hermes profile
    if delete_profile:
        hermes = find_hermes_binary()
        profiles_root = get_profiles_root()
        try:
            result = subprocess.run(
                [hermes, "profile", "delete", name, "--yes"],
                capture_output=True, text=True, timeout=15,
                env={**os.environ, "HERMES_HOME": str(profiles_root.parent)},
            )
            if result.returncode != 0:
                # Fallback: manually remove the directory
                profile_dir = profiles_root / name
                if profile_dir.exists():
                    shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception as exc:
            logger.warning("Failed to delete profile via CLI: %s, removing dir directly", exc)
            profile_dir = profiles_root / name
            if profile_dir.exists():
                shutil.rmtree(profile_dir, ignore_errors=True)

    # Remove from registry
    wf.unlink()
    logger.info("Worker '%s' removed (delete_profile=%s)", name, delete_profile)
    return {"status": "removed", "worker": name}


def get_worker(name: str) -> dict | None:
    """Get worker registry data."""
    wf = _worker_file(name)
    if not wf.exists():
        return None
    return json.loads(wf.read_text())


def list_workers() -> list[dict]:
    """List all registered Agora workers."""
    d = get_registry_dir("workers")
    workers = []
    for f in d.glob("*.json"):
        try:
            workers.append(json.loads(f.read_text()))
        except Exception:
            pass
    return workers


def list_available_templates() -> list[dict]:
    """List all role templates that can be used to create workers."""
    return list_templates()


def update_worker_session(name: str, session_id: str | None) -> None:
    """Update a worker's session_id for future --resume calls.

    Called after each agent spawn so the next spawn reuses the same
    conversation context (kanban tasks + discussion share one session).
    Pass ``None`` or empty string to clear the session (forces a fresh
    session on next spawn).
    """
    wf = _worker_file(name)
    if not wf.exists():
        return
    data = json.loads(wf.read_text())
    data["session_id"] = session_id or None
    wf.write_text(json.dumps(data, indent=2))


def get_worker_session(name: str) -> str | None:
    """Get a worker's current session_id (or None if never spawned)."""
    wf = _worker_file(name)
    if not wf.exists():
        return None
    data = json.loads(wf.read_text())
    return data.get("session_id")
