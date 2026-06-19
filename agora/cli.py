"""Agora CLI — command-line interface for the Agora platform.

Usage:
    agora serve          Start the coordinator server
    agora --version      Show version
"""
from __future__ import annotations

import argparse
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
