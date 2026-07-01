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

__version__ = "0.8.0"


def register(ctx) -> None:
    """Plugin entry point — called once by Hermes plugin loader."""
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
        description="Manage Agora discussions: list, show, discuss, result",
    )

    logger.info("Agora plugin registered (4 tools + 3 project tools + 7 worker/team tools + 4 leader tools + dashboard API + /agora command + hermes agora CLI + hooks with self-drive)")
