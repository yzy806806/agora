"""Agora — Multi-role deliberation plugin for Hermes.

Registers tools that let agents raise motions, an LLM-driven discussion
engine that simulates architect/developer/reviewer debate, and bridges
discussion outcomes to the Hermes kanban board for task dispatch.

Install:
    hermes plugins install yzy806806/agora
    hermes agora setup        # deploy the bundled skills

Usage:
    /agora discuss "Should we use PostgreSQL instead of SQLite?"
    # or agent calls agora_raise_motion() during task execution
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__version__ = "2.0.8"


def deploy_bundled_skills() -> list[str]:
    """Copy the bundled skills into ``<hermes_home>/skills/collaboration/``.

    Deliberately NOT called from :func:`register`: plugin registration must not
    write to disk. Run it explicitly via ``hermes agora setup`` (or implicitly
    when a project is started, which is itself an explicit user action).

    Returns the skill names deployed. Overwrites stale copies; skills the user
    has edited under a different name are never touched.
    """
    import shutil
    from pathlib import Path

    from .agora.utils import get_hermes_root

    plugin_skills = Path(__file__).resolve().parent / "skills"
    if not plugin_skills.is_dir():
        return []

    global_skills = get_hermes_root() / "skills"
    deployed: list[str] = []
    for skill_dir in sorted(plugin_skills.iterdir()):
        if not skill_dir.is_dir():
            continue
        # agora-awareness → collaboration/agora-awareness
        dest = global_skills / "collaboration" / skill_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        for f in skill_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, dest / f.name)
        deployed.append(skill_dir.name)

    logger.info("Deployed %d bundled skills to %s", len(deployed), global_skills)
    return deployed


def register(ctx) -> None:
    """Plugin entry point — called once by Hermes plugin loader.

    Registers tools, hooks and the CLI subcommand only. No filesystem writes:
    skill deployment is an explicit ``hermes agora setup`` step.
    """
    from .tools import register_all_tools
    from .cli import setup_agora_cli, handle_agora_cli
    from .hooks import register_hooks

    logger.info("Agora plugin v%s registering...", __version__)
    register_all_tools(ctx)
    register_hooks(ctx)

    # Register `hermes agora` CLI subcommand
    ctx.register_cli_command(
        "agora",
        help="Agora — multi-role deliberation",
        setup_fn=setup_agora_cli,
        handler_fn=handle_agora_cli,
        description="Manage Agora projects and discussions: setup, list, show, discuss, result",
    )

    logger.info("Agora plugin v%s registered (20 tools + dashboard API + /agora command + CLI + 3 hooks + project boards)", __version__)
