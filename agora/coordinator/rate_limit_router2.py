"""Phase 9.4: Rate limit check + config update endpoints.

Split from rate_limit_router.py to keep files under 80 lines.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from .config import settings
from .rbac import Permission, Role, get_current_role, requires
from .storage import Storage
from .token_rate_limiter import TokenRateLimiter

router = APIRouter()

_storage: Optional[Storage] = None
_token_limiter: Optional[TokenRateLimiter] = None


def init_rate_limit_deps2(storage: Storage, limiter: TokenRateLimiter) -> None:
    global _storage, _token_limiter
    _storage = storage
    _token_limiter = limiter


@router.post("/agents/{agent_id}/rate-limit/check")
@requires(Permission.AGENT_REGISTER)
async def check_rate_limit(
    agent_id: str, body: dict,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Pre-check: can agent make a call of N tokens? No deduction."""
    if _token_limiter is None or _storage is None:
        raise HTTPException(status_code=503, detail="Not initialized")
    agent = await _storage.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    estimated = body.get("estimated_tokens", 0)
    status = _token_limiter.get_status(agent_id)
    allowed = status["tokens_available"] >= estimated
    return {
        "agent_id": agent_id,
        "allowed": allowed,
        "tokens_available": status["tokens_available"],
        "wait_seconds": _token_limiter.time_until_available(
            agent_id, estimated) if not allowed else 0,
    }


@router.patch("/agents/{agent_id}/config")
@requires(Permission.CONFIG_WRITE)
async def update_agent_config(
    agent_id: str, body: dict,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Update agent config including TPM limits. Admin only."""
    if _storage is None or _token_limiter is None:
        raise HTTPException(status_code=503, detail="Not initialized")
    agent = await _storage.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    tpm_limit = body.get("tpm_limit")
    tpm_burst = body.get("tpm_burst_factor")
    if tpm_limit is not None:
        burst = tpm_burst if tpm_burst is not None else 1.5
        _token_limiter.configure(agent_id, tpm_limit, burst)
        await _storage.update_agent_tpm_config(
            agent_id, tpm_limit=tpm_limit,
            tpm_burst_factor=tpm_burst,
        )
    return {"agent_id": agent_id, "updated": list(body.keys())}
