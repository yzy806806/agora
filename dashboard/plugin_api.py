"""Agora dashboard plugin — backend API routes.

Mounted at /api/plugins/agora/ by the Hermes dashboard plugin system.
Provides REST endpoints for listing/viewing/creating motions.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agora", tags=["agora"])

# Storage is imported lazily so the module can be loaded by the
# dashboard plugin system without the full Hermes plugin context.
_db = None


def _get_db():
    global _db
    if _db is None:
        import sys
        import os
        # Resolve the plugin root from this file's location
        plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if plugin_root not in sys.path:
            sys.path.insert(0, plugin_root)
        from agora.storage import motions as motions_db
        _db = motions_db
    return _db


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CreateMotionRequest(BaseModel):
    title: str
    description: str = ""
    rounds: int = 3
    participants: list[str] = Field(default_factory=lambda: ["architect", "developer", "reviewer"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/motions")
async def list_motions(status: str = "all", limit: int = 20):
    """List discussions."""
    db = _get_db()
    motions = db.list_motions(status_filter=status, limit=limit)
    return {"motions": motions, "total": len(motions)}


@router.get("/motions/{motion_id}")
async def get_motion(motion_id: str):
    """Get a motion with its messages."""
    db = _get_db()
    motion = db.get_motion(motion_id)
    if motion is None:
        raise HTTPException(status_code=404, detail="Motion not found")
    messages = db.get_messages(motion_id)
    return {**motion, "messages": messages}


@router.post("/motions")
async def create_motion(req: CreateMotionRequest):
    """Create a new motion and start discussion in background."""
    db = _get_db()
    motion = db.create_motion(
        title=req.title,
        description=req.description,
        max_rounds=req.rounds,
        source="user",
        participants=req.participants,
    )
    # TODO: start discussion driver — needs ctx reference
    # For now, just create the motion. Discussion can be started
    # via /agora discuss command or agora_raise_motion tool.
    return motion


@router.get("/motions/{motion_id}/messages")
async def get_messages(motion_id: str, round: Optional[int] = None):
    """Get messages for a motion."""
    db = _get_db()
    messages = db.get_messages(motion_id, round_num=round)
    return {"motion_id": motion_id, "messages": messages, "total": len(messages)}


@router.get("/motions/{motion_id}/result")
async def get_result(motion_id: str):
    """Get the result of a closed motion."""
    db = _get_db()
    motion = db.get_motion(motion_id)
    if motion is None:
        raise HTTPException(status_code=404, detail="Motion not found")
    if motion["status"] != "closed":
        return {"motion_id": motion_id, "status": motion["status"], "message": "Still in progress"}
    return {
        "motion_id": motion_id,
        "title": motion["title"],
        "decision": motion.get("decision"),
        "rationale": motion.get("rationale"),
        "action_items": motion.get("action_items", []),
        "closed_at": motion.get("closed_at"),
    }


@router.get("/stats")
async def get_stats():
    """Get summary statistics for the dashboard."""
    db = _get_db()
    all_motions = db.list_motions(status_filter="all", limit=100)
    active = [m for m in all_motions if m["status"] != "closed"]
    closed = [m for m in all_motions if m["status"] == "closed"]
    adopted = [m for m in closed if m.get("decision") == "adopted"]
    rejected = [m for m in closed if m.get("decision") == "rejected"]

    return {
        "total": len(all_motions),
        "active": len(active),
        "closed": len(closed),
        "adopted": len(adopted),
        "rejected": len(rejected),
    }
