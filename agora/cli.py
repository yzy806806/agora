"""Agora CLI — command-line interface for the Agora platform.

Usage:
    agora serve          Start the coordinator server
    agora daemon         Run the bootstrap daemon (self-driving loop)
    agora --version      Show version
"""
from __future__ import annotations

import argparse
import asyncio
import sys


def _cmd_serve(args: argparse.Namespace) -> None:
    """Start the Agora coordinator server."""
    from agora.coordinator.main import main as serve_main
    from agora.coordinator.config import settings
    if args.port:
        settings.port = args.port
    if args.host:
        settings.host = args.host
    serve_main()


def _cmd_daemon(args: argparse.Namespace) -> None:
    """Run the bootstrap daemon — self-driving development loop."""
    from agora.coordinator.config import settings
    from agora.coordinator.bootstrap.daemon import run_daemon

    db_path = settings.get_db_path()
    coordinator_url = f"http://{settings.host}:{settings.port}"

    asyncio.run(run_daemon(
        db_path=db_path,
        coordinator_url=coordinator_url,
        interval_minutes=args.interval,
        dry_run=args.dry_run,
        once=args.once,
    ))


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the agora CLI."""
    from agora import __version__

    parser = argparse.ArgumentParser(
        prog="agora",
        description="Agora — Multi-Agent Deliberation Platform",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"agora {__version__}",
    )

    sub = parser.add_subparsers(dest="command")

    # serve
    sp_serve = sub.add_parser("serve", help="Start the coordinator server")
    sp_serve.add_argument("--host", default=None, help="Bind host")
    sp_serve.add_argument("--port", type=int, default=None, help="Bind port")
    sp_serve.set_defaults(func=_cmd_serve)

    # daemon
    sp_daemon = sub.add_parser("daemon", help="Run the bootstrap daemon")
    sp_daemon.add_argument("--interval", type=int, default=30,
                           help="Check interval in minutes (default: 30)")
    sp_daemon.add_argument("--dry-run", action="store_true",
                           help="Only detect work, don't execute")
    sp_daemon.add_argument("--once", action="store_true",
                           help="Run once and exit (no loop)")
    sp_daemon.set_defaults(func=_cmd_daemon)

    # migrate
    from agora.cli_migrate import add_migrate_parser
    add_migrate_parser(sub)

    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
