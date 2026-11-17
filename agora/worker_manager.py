"""Worker profile manager — create, list, remove Hermes profiles from templates.

A "worker" is a Hermes profile with:
  - config.yaml    (with .env, both provisioned by core from the source profile)
  - SOUL.md        (role identity, rendered from template)
  - MEMORY.md      (empty initially, accumulates experience over time)
  - USER.md        (empty initially)
  - skills/        (profile-local skills directory, independent from global)
  - description    (set via `hermes profile describe`)

Workers persist across projects. Their memory, skills, and identity are
personal — they carry experience from one project to the next, just like
a real employee.

There is no separate "leader" concept at the profile level. A leader is
simply a worker created from the "leader" template. Heartbeat scheduling
lives on the *project*, not the profile — so the same leader profile can
manage multiple projects with independent heartbeat intervals and
sessions, while sharing a single MEMORY.md (experience).
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
    get_hermes_root,
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
    clone_from: str | None = None,
    model: str | None = None,
    extra_config: dict | None = None,
) -> dict:
    """Create a new worker profile from a role template.

    This creates a full Hermes profile with:
    - config.yaml and .env provisioned by core (`hermes profile create
      --clone` does the copy and tightens the .env to owner-only)
    - SOUL.md rendered from the role template
    - Empty MEMORY.md and USER.md
    - Independent skills/ directory
    - Profile description set for kanban routing

    Args:
        name:        Profile name (lowercase, alphanumeric, e.g. "alice")
        role:        Template role key (architect/developer/reviewer/tester/devops/researcher/writer/leader)
        clone_from:  Source profile for core to clone from. Default (None)
                     clones from the active profile: HERMES_HOME is pointed at
                     the global root, so that resolves to the profile holding the
                     user's real configuration and keys. Set it to inherit from a
                     specific existing profile instead.
        model:       Override model for this worker (default: from template or inherit)
        extra_config: Additional config overrides (rarely needed)

    Returns:
        dict with creation status and worker info
    """
    # Validate name — normalise to lowercase (webui may pass display names)
    name = name.strip()
    if name and name != name.lower():
        name = name.lower()
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

    # Step 1: Provision the profile through core.
    #
    # Catalog rule 11: credentials come through Hermes, never from files. Core's
    # own provisioning copies config.yaml and .env for the new profile (tightening
    # the copy to owner-only), so the plugin asks for a profile instead of reading
    # the user's credential file itself. The clone source is always explicit
    # (``--clone-from default`` unless the caller names one) so the worker
    # inherits the profile that holds the user's real configuration and keys.
    hermes = find_hermes_binary()
    create_cmd = _profile_create_command(hermes, name, description, clone_from)
    try:
        result = subprocess.run(
            create_cmd,
            capture_output=True, text=True, timeout=90,
            env={**os.environ, "HERMES_HOME": str(profiles_root.parent)},
        )
        if result.returncode != 0:
            return {
                "error": f"Failed to create profile: {result.stderr.strip() or result.stdout.strip()}",
                "command": " ".join(create_cmd),
            }
    except Exception as exc:
        return {"error": f"Failed to create profile: {exc}"}

    # Step 1a: Undo the skills copy that cloning implies.
    #
    # `--no-skills` writes core's opt-out marker and does nothing else, but it
    # cannot be combined with a clone, so the clone brings the source profile's
    # whole skills tree along and this puts the profile back to the opted-out
    # shape. Both halves matter: an empty skills/ alone would be re-seeded by
    # the next `hermes update`, and the marker alone would leave the inherited
    # tree in place.
    if not clone_from:
        _drop_cloned_skills(profile_dir)

    # Step 1b: Ensure compression.in_place: true so session IDs don't change
    # on context compression — --resume <session_id> always works.
    ensure_in_place_compression(profile_dir / "config.yaml")

    # Step 1c: Inject skills.external_dirs so the worker can read global
    # shared skills (~/.hermes/skills/) while keeping its own profile-local
    # skills/ directory for skills it creates via skill_manage.
    # Without this, a worker spawned with -p <profile> would only see its
    # own (nearly empty) skills/ dir and be blind to the 40+ shared skills.
    _inject_external_skills(profile_dir / "config.yaml", profiles_root.parent)

    # Step 1d: Link global plugins into the profile's plugins/ directory.
    # Workers spawned with -p <profile> have HERMES_HOME pointing at their
    # profile directory, so Hermes only scans <profile>/plugins/ for plugins.
    # Without this, workers can't see plugins installed in the global
    # ~/.hermes/plugins/ (e.g. agora itself) and their tools are unavailable.
    _link_global_plugins(profile_dir, profiles_root.parent)

    # Step 2: Write SOUL.md
    if template is not None:
        soul_path = profile_dir / "SOUL.md"
        soul_content = render_soul(template, name)
        try:
            soul_path.write_text(soul_content)
        except Exception as exc:
            logger.warning("Failed to write SOUL.md for %s: %s", name, exc)
    else:
        # Role 'custom': the caller writes SOUL.md (Step 2 note above). Core's
        # clone brought the source profile's SOUL.md along, so drop it: until the
        # caller writes its own, the worker must not answer as the operator.
        try:
            (profile_dir / "SOUL.md").unlink()
        except FileNotFoundError:
            pass  # nothing was cloned to drop
        except OSError as exc:
            # Not silent: a copy left behind means the worker answers in the
            # operator's voice until the caller writes its own SOUL.md.
            logger.warning(
                "Failed to drop the cloned SOUL.md for %s: %s — until the "
                "caller writes one, this worker may speak as the operator.",
                name, exc,
            )

    # Step 3: Ensure memories/MEMORY.md exists (Hermes memory tool reads/writes here)
    # NOTE: Hermes v0.18 memory tool uses <profile>/memories/MEMORY.md, NOT <profile>/MEMORY.md
    memories_dir = profile_dir / "memories"
    try:
        memories_dir.mkdir(parents=True, exist_ok=True)
        memory_path = memories_dir / "MEMORY.md"
        if not memory_path.exists():
            memory_path.write_text(f"# {name} Memory\n\nPersonal experience and learned facts.\n")
        # Do NOT overwrite existing memory — workers accumulate experience
        # across sessions. Only create if missing.
    except Exception as exc:
        logger.warning("Failed to write memories/MEMORY.md for %s: %s", name, exc)

    # Step 4: Ensure memories/USER.md exists
    try:
        user_path = memories_dir / "USER.md"
        if not user_path.exists() or user_path.stat().st_size == 0:
            user_path.write_text(f"# {name}\n\nRole: {display_name}\n")
    except Exception as exc:
        logger.warning("Failed to write memories/USER.md for %s: %s", name, exc)

    # Step 5: Ensure skills/ dir exists and seed with agora-awareness skill
    skills_dir = profile_dir / "skills"
    try:
        skills_dir.mkdir(parents=True, exist_ok=True)
        # Seed the agora-awareness skill so every worker understands the system
        _seed_agora_skill(skills_dir)
    except Exception as exc:
        logger.warning("Failed to create skills dir for %s: %s", name, exc)

    # Step 6: Override model if specified or from template
    effective_model = model or (template.get("model") if template else None)
    if effective_model:
        patch_config_model(profile_dir / "config.yaml", effective_model)

    # Step 6b: Write toolsets from template into config.yaml
    # The template defines which toolsets each role needs. Without this,
    # workers inherit the global config's toolsets (usually hermes-cli = everything),
    # including browser, tts, vision, computer_use etc. that they don't need.
    template_toolsets = template.get("toolsets") if template else None
    if template_toolsets:
        _patch_config_toolsets(profile_dir / "config.yaml", template_toolsets)

    # Step 7: Register in the worker registry
    is_leader = template.get("is_leader", False) if template else False
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
        "session_ids": {},  # project_name → session_id (per-project context isolation)
        "is_leader": is_leader,
    }
    _worker_file(name).write_text(json.dumps(worker_data, indent=2))

    logger.info(
        "Worker '%s' created (role=%s, model=%s, dir=%s, is_leader=%s)",
        name, role, effective_model or "inherited", profile_dir, is_leader,
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


def update_worker_session(name: str, session_id: str | None, project: str | None = None) -> None:
    """Update a worker's session_id for a specific project.

    Per-project session isolation: the same worker (e.g. a leader) can
    have different sessions for different projects.  If ``project`` is
    None, updates the legacy top-level ``session_id`` field for backward
    compatibility.

    Called after each agent spawn so the next spawn reuses the same
    conversation context within that project.
    Pass ``None`` or empty string to clear the session (forces a fresh
    session on next spawn).
    """
    import fcntl

    wf = _worker_file(name)
    if not wf.exists():
        return
    # Use an exclusive file lock to prevent concurrent read-modify-write
    # races when multiple discussion drivers update the same worker's
    # session simultaneously.
    lock_path = wf.with_suffix(".lock")
    try:
        with open(lock_path, "w") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            data = json.loads(wf.read_text())
            if project:
                session_map = data.get("session_ids", {})
                if session_id:
                    session_map[project] = session_id
                else:
                    session_map.pop(project, None)
                data["session_ids"] = session_map
            else:
                data["session_id"] = session_id or None
            wf.write_text(json.dumps(data, indent=2))
    except (OSError, IOError):
        # Fallback: no lock, direct write (best-effort)
        try:
            data = json.loads(wf.read_text())
            if project:
                session_map = data.get("session_ids", {})
                if session_id:
                    session_map[project] = session_id
                else:
                    session_map.pop(project, None)
                data["session_ids"] = session_map
            else:
                data["session_id"] = session_id or None
            wf.write_text(json.dumps(data, indent=2))
        except Exception:
            pass


def get_worker_session(name: str, project: str | None = None) -> str | None:
    """Get a worker's session_id for a specific project (or legacy global).

    Per-project isolation: if ``project`` is given, returns the session
    stored under ``session_ids[project]``.  Falls back to the legacy
    top-level ``session_id`` if the project-specific entry doesn't exist.
    """
    wf = _worker_file(name)
    if not wf.exists():
        return None
    data = json.loads(wf.read_text())
    if project:
        return data.get("session_ids", {}).get(project) or data.get("session_id")
    return data.get("session_id")


def _seed_agora_skill(skills_dir: Path) -> None:
    """Copy the agora-awareness skill into a worker's skills directory.

    This gives every new worker an understanding of how Agora works:
    the team structure, kanban commands, discussion protocol, and
    available tools.

    Prefers the plugin's own bundled copy so seeding works even when
    ``hermes agora setup`` was never run; falls back to the deployed copy under
    the Hermes home.
    """
    import shutil

    candidates = [
        # Bundled with the plugin (authoritative).
        Path(__file__).resolve().parent.parent / "skills" / "agora-awareness" / "SKILL.md",
        # Deployed by `hermes agora setup`.
        get_hermes_root() / "skills" / "collaboration" / "agora-awareness" / "SKILL.md",
        get_hermes_root() / "skills" / "agora-awareness" / "SKILL.md",
    ]
    source = next((c for c in candidates if c.exists()), None)
    if source is None:
        logger.warning("agora-awareness skill not found — skipping seed")
        return

    dest_dir = skills_dir / "agora-awareness"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "SKILL.md"
    if not dest.exists():
        shutil.copy2(source, dest)
        logger.info("Seeded agora-awareness skill to %s", dest)


def _patch_config_toolsets(config_path: Path, toolsets: list[str]) -> None:
    """Write toolsets into the profile's config.yaml platform_toolsets.cli.

    This overrides the global config's toolsets (usually 'hermes-cli' which
    includes everything) with only the toolsets the role needs.
    """
    try:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        if cfg is None:
            cfg = {}
        if "platform_toolsets" not in cfg:
            cfg["platform_toolsets"] = {}
        cfg["platform_toolsets"]["cli"] = toolsets
        with open(config_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
        logger.info("Wrote toolsets %s to %s", toolsets, config_path)
    except Exception as exc:
        logger.warning("Failed to patch toolsets in %s: %s", config_path, exc)


NO_BUNDLED_SKILLS_MARKER = ".no-bundled-skills"
_NO_BUNDLED_SKILLS_TEXT = (
    "This profile opted out of bundled-skill seeding (`hermes profile create --no-skills`).\n"
    "Delete this file to re-enable sync on the next `hermes update`.\n"
)


def _profile_create_command(
    hermes: str, name: str, description: str, clone_from: str | None,
) -> list[str]:
    """The ``hermes profile create`` invocation for a worker.

    Always clones — that is how core supplies ``config.yaml`` and ``.env`` under
    catalog rule 11 — and the source defaults to the ``default`` profile, the one
    holding the operator's config and keys (what a bare ``--clone`` resolved to).

    ``--no-skills`` is deliberately absent: core refuses it alongside any clone
    option (``cloning explicitly copies skills from the source profile``), and
    pairing the two made ``agora_create_worker`` fail outright for every caller
    between v2.0.12 and v2.0.13. The skills the clone brings along are undone
    afterwards by :func:`_drop_cloned_skills`, which reaches the state core's
    opt-out flag would have produced.
    """
    return [
        hermes, "profile", "create", name,
        "--description", description,
        "--clone-from", clone_from or "default",
    ]


def _drop_cloned_skills(profile_dir: Path) -> None:
    """Empty the cloned ``skills/`` tree and write core's opt-out marker.

    Core's ``--no-skills`` and its clone options are mutually exclusive, so a
    worker provisioned by cloning inherits the source profile's whole skills
    tree. Agora wants the shape ``--no-skills``
    would have left instead: an empty profile-local ``skills/`` directory plus
    ``.no-bundled-skills``, which core's seeder and ``hermes update`` both read
    as "leave this profile's skills alone".

    Shared skills stay reachable through ``skills.external_dirs`` (Step 1c), and
    the worker still writes new skills into its own ``skills/`` directory.

    Only the default clone is undone: an explicit ``clone_from`` is a request for
    that profile as it is, skills included, so its tree is left untouched.
    """
    skills_dir = profile_dir / "skills"
    if skills_dir.is_dir():
        for child in skills_dir.iterdir():
            try:
                if child.is_dir() and not child.is_symlink():
                    # Not ignore_errors: a half-removed tree would otherwise pass
                    # for a clean one, and this profile is supposed to see only
                    # its own skills plus the shared external dirs.
                    shutil.rmtree(child)
                else:
                    child.unlink()
            except OSError as exc:
                # Not fatal — the worker runs fine with inherited skills — but
                # say so rather than implying a clean profile-local tree.
                logger.warning("Could not remove cloned skill %s: %s", child, exc)

    try:
        (profile_dir / NO_BUNDLED_SKILLS_MARKER).write_text(_NO_BUNDLED_SKILLS_TEXT)
    except OSError as exc:
        logger.warning(
            "Could not write %s for %s: %s — the next `hermes update` may "
            "re-seed bundled skills into this worker.",
            NO_BUNDLED_SKILLS_MARKER, profile_dir.name, exc,
        )


def _inject_external_skills(config_path: Path, hermes_root: Path) -> None:
    """Inject skills.external_dirs into the profile's config.yaml.

    Workers spawned with -p <profile> have HERMES_HOME pointing at their
    profile directory, so ``get_skills_dir()`` returns the profile-local
    skills/ dir (nearly empty for new workers).  By adding the global
    ~/.hermes/skills/ as an external dir, workers can read all shared
    skills while keeping their own skills/ dir for personal skills they
    create via skill_manage.
    """
    try:
        import yaml

        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
        if not isinstance(cfg, dict):
            return

        skills_cfg = cfg.get("skills")
        if not isinstance(skills_cfg, dict):
            skills_cfg = {}

        global_skills = str(hermes_root / "skills")
        ext_dirs = skills_cfg.get("external_dirs", [])
        if not isinstance(ext_dirs, list):
            ext_dirs = []
        if global_skills not in ext_dirs:
            ext_dirs.append(global_skills)
            skills_cfg["external_dirs"] = ext_dirs
            cfg["skills"] = skills_cfg

            with open(config_path, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
            logger.info("Injected skills.external_dirs=%s into %s", ext_dirs, config_path)
    except Exception as exc:
        logger.warning("Failed to inject external_dirs into %s: %s", config_path, exc)


def _link_global_plugins(profile_dir: Path, hermes_root: Path) -> None:
    """Symlink every plugin in the global plugins/ dir into the profile.

    Workers spawned with -p <profile> have HERMES_HOME pointing at their
    profile directory, so Hermes only scans ``<profile>/plugins/`` during
    plugin discovery.  Plugins installed globally (``~/.hermes/plugins/``)
    are invisible unless we link them here.

    Uses symlinks so updates to the global plugin are reflected immediately
    without re-copying.  Existing entries (real dirs or symlinks) are left
    untouched to respect manual overrides.
    """
    try:
        global_plugins = hermes_root / "plugins"
        if not global_plugins.is_dir():
            return

        profile_plugins = profile_dir / "plugins"
        profile_plugins.mkdir(parents=True, exist_ok=True)

        for entry in global_plugins.iterdir():
            if not entry.is_dir() and not entry.is_symlink():
                continue
            link_path = profile_plugins / entry.name
            # Don't overwrite an existing entry (manual override)
            if link_path.exists() or link_path.is_symlink():
                continue
            try:
                link_path.symlink_to(entry.resolve())
                logger.info("Linked plugin %s → %s", link_path, entry)
            except OSError as exc:
                logger.warning("Failed to symlink plugin %s: %s", entry.name, exc)
    except Exception as exc:
        logger.warning("Failed to link global plugins into %s: %s", profile_dir, exc)
