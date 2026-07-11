"""Agora — Multi-role deliberation plugin for Hermes.

Registers tools that let agents raise motions, an LLM-driven discussion
engine that simulates architect/developer/reviewer debate, and bridges
discussion outcomes to the Hermes kanban board for task dispatch.

Install:
    hermes plugins install yzy806806/agora

Usage:
    /agora discuss "Should we use PostgreSQL instead of SQLite?"
    # or agent calls agora_raise_motion() during task execution
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__version__ = "1.5.6"


def _deploy_skills() -> None:
    """Copy bundled skills (agora-awareness, agora-deliberation) to the global
    ~/.hermes/skills/ directory so they're available to all profiles.

    Called once at plugin registration. Overwrites stale copies silently;
    existing user-edited skills under different names are never touched.
    """
    import shutil
    from pathlib import Path

    plugin_skills = Path(__file__).resolve().parent / "skills"
    if not plugin_skills.is_dir():
        return

    global_skills = Path.home() / ".hermes" / "skills"
    global_skills.mkdir(parents=True, exist_ok=True)

    for skill_dir in plugin_skills.iterdir():
        if not skill_dir.is_dir():
            continue
        # agora-awareness → collaboration/agora-awareness
        # agora-deliberation → collaboration/agora-deliberation
        dest = global_skills / "collaboration" / skill_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        for f in skill_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, dest / f.name)

    logger.debug("Agora skills deployed to %s", global_skills)


def register(ctx) -> None:
    """Plugin entry point — called once by Hermes plugin loader."""
    from .tools import register_all_tools
    from .cli import setup_agora_cli, handle_agora_cli
    from .hooks import register_hooks

    logger.info("Agora plugin v%s registering...", __version__)
    register_all_tools(ctx)
    register_hooks(ctx)

    # Deploy bundled skills to global ~/.hermes/skills/
    _deploy_skills()

    # Register `hermes agora` CLI subcommand
    ctx.register_cli_command(
        "agora",
        help="Agora — multi-role deliberation",
        setup_fn=setup_agora_cli,
        handler_fn=handle_agora_cli,
        description="Manage Agora discussions: list, show, discuss, result",
    )

    logger.info("Agora plugin v%s registered (16 tools + dashboard API + /agora command + CLI + 3 hooks + session manager + project boards + skills)", __version__)
