"""Agora CLI — `hermes agora` subcommand.

Usage:
    hermes agora list               — list discussions
    hermes agora show <motion_id>   — show discussion messages
    hermes agora result <motion_id> — show discussion result
    hermes agora discuss <topic>    — start a new discussion
    hermes agora stats              — show summary statistics
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def setup_agora_cli(subparser: argparse.ArgumentParser) -> None:
    """Set up the `hermes agora` subcommand arguments."""
    sub = subparser.add_subparsers(dest="agora_command")

    # list
    sp_list = sub.add_parser("list", help="List discussions")
    sp_list.add_argument("--status", default="all", choices=["active", "closed", "all"])
    sp_list.add_argument("--limit", type=int, default=20)

    # show
    sp_show = sub.add_parser("show", help="Show discussion messages")
    sp_show.add_argument("motion_id", help="Motion ID")

    # result
    sp_result = sub.add_parser("result", help="Show discussion result")
    sp_result.add_argument("motion_id", help="Motion ID")

    # discuss
    sp_discuss = sub.add_parser("discuss", help="Start a new discussion")
    sp_discuss.add_argument("topic", help="Discussion topic")
    sp_discuss.add_argument("--description", "-d", default="", help="Detailed description")
    sp_discuss.add_argument("--rounds", type=int, default=3, help="Max rounds (default: 3)")

    # stats
    sub.add_parser("stats", help="Show summary statistics")


def handle_agora_cli(args: argparse.Namespace) -> int:
    """Handle `hermes agora` CLI commands. Returns exit code."""
    cmd = getattr(args, "agora_command", None)
    if not cmd:
        print("Usage: hermes agora {list|show|result|discuss|stats}")
        return 1

    try:
        from .agora.storage import motions as db
    except ImportError:
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
        from agora.storage import motions as db

    if cmd == "list":
        motions = db.list_motions(status_filter=args.status, limit=args.limit)
        if not motions:
            print("No discussions found.")
            return 0
        print(f"{'ID':<20} {'Status':<12} {'Decision':<15} {'Source':<8} {'Title'}")
        print("-" * 90)
        for m in motions:
            print(
                f"{m['id']:<20} {m['status']:<12} {m.get('decision') or '-':<15} "
                f"{m.get('source', 'user'):<8} {m['title'][:50]}"
            )
        print(f"\nTotal: {len(motions)}")
        return 0

    elif cmd == "show":
        motion = db.get_motion(args.motion_id)
        if motion is None:
            print(f"Motion '{args.motion_id}' not found.")
            return 1
        messages = db.get_messages(args.motion_id)
        print(f"{'=' * 80}")
        print(f"Motion: {motion['title']}")
        print(f"Status: {motion['status']} | Round: {motion['current_round']}/{motion['max_rounds']}")
        if motion.get("description"):
            print(f"Description: {motion['description']}")
        print(f"{'=' * 80}")
        for msg in messages:
            print(f"\n[{msg['role']} R{msg['round_num']}] ({msg['stance']})")
            print(msg["content"])
        return 0

    elif cmd == "result":
        motion = db.get_motion(args.motion_id)
        if motion is None:
            print(f"Motion '{args.motion_id}' not found.")
            return 1
        if motion["status"] != "closed":
            print(f"Motion is still {motion['status']}.")
            return 0
        print(f"Decision: {motion.get('decision', '?')}")
        print(f"Summary: {motion.get('rationale', '')}")
        print(f"\nAction Items:")
        for ai in motion.get("action_items", []):
            print(f"  • {ai}")
        return 0

    elif cmd == "discuss":
        # Create the motion — actual discussion requires ctx.llm which
        # is only available in gateway/agent context, not CLI.
        # For CLI we create the motion and print instructions.
        motion = db.create_motion(
            title=args.topic,
            description=args.description,
            max_rounds=args.rounds,
            source="user",
        )
        print(f"Motion created: {motion['id']}")
        print(f"Title: {motion['title']}")
        print(f"\nTo start the discussion, use:")
        print(f"  /agora discuss {args.topic}")
        print(f"\nOr in a Hermes session, the agent will pick it up.")
        return 0

    elif cmd == "stats":
        motions = db.list_motions(status_filter="all", limit=100)
        active = [m for m in motions if m["status"] != "closed"]
        closed = [m for m in motions if m["status"] == "closed"]
        adopted = [m for m in closed if m.get("decision") == "adopted"]
        rejected = [m for m in closed if m.get("decision") == "rejected"]
        print(f"Agora Statistics")
        print(f"  Total discussions:  {len(motions)}")
        print(f"  Active:             {len(active)}")
        print(f"  Closed:             {len(closed)}")
        print(f"    Adopted:          {len(adopted)}")
        print(f"    Rejected:         {len(rejected)}")
        return 0

    return 1
