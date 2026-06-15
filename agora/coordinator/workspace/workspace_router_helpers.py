"""Workspace REST API helpers — agent_id extraction + Range parsing.

Split from workspace_router.py to stay under 80 lines.
"""
from __future__ import annotations

import re

from fastapi import HTTPException, Request

from ..token_manager import TokenManager


def _extract_agent_id(request: Request) -> str:
    """Extract agent_id from JWT or agent token in Authorization header."""
    auth: str = request.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authorization required")
    # Try JWT decode via app.state.token_mgr
    token_mgr: TokenManager | None = getattr(
        request.app.state, "token_mgr", None,
    )
    if token_mgr and token_mgr._secret:
        try:
            payload = token_mgr.validate_token(token)
            return payload.agent_id
        except ValueError:
            pass
    # Fallback: agent tokens (ag-*) use token itself as identifier
    if token.startswith("ag-"):
        return token
    raise HTTPException(status_code=401, detail="Invalid token")


def parse_range_header(
    range_header: str, total_size: int,
) -> tuple[int, int]:
    """Parse HTTP Range header (bytes=0-1023).

    Returns (offset, length). Raises 400 on malformed input,
    416 on unsatisfiable range.
    """
    match = re.match(r"^bytes=(\d*)-(\d*)$", range_header)
    if not match:
        raise HTTPException(status_code=400, detail="Invalid Range header")
    start_str, end_str = match.group(1), match.group(2)
    if start_str == "" and end_str == "":
        raise HTTPException(status_code=400, detail="Invalid Range header")
    if start_str == "":
        # suffix range: bytes=-500 → last 500 bytes
        suffix = int(end_str)
        offset = max(0, total_size - suffix)
        return offset, total_size - offset
    start = int(start_str)
    end = int(end_str) if end_str else total_size - 1
    if start >= total_size or start > end:
        raise HTTPException(status_code=416, detail="Range Not Satisfiable")
    end = min(end, total_size - 1)
    return start, end - start + 1
