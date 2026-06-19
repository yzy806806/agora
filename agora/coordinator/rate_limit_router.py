"""Rate limit HTTP API endpoints.

GET  /agents/{agent_id}/rate-limit          — status
POST /agents/{agent_id}/rate-limit/report   — report usage
POST /agents/{agent_id}/rate-limit/check    — pre-check
PATCH /agents/{agent_id}/config             — update TPM config
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from .rbac import Permission, Role, get_current_role, requires
from .storage import Storage
from .rate_limiter import TokenRateLimiter

logger = logging.getLogger(__name__)

router = APIRouter()

_storage: Optional[Storage] = None
_token_limiter: Optional[TokenRateLimiter] = None


def init_rate_limit_deps(
    storage: Storage, limiter: TokenRateLimiter,
) -> None:
    """Initialize rate limit router dependencies."""
    global _storage, _token_limiter
    _storage = storage
    _token_limiter = limiter

# Alias for backward compat with main.py import
init_rate_limit_deps2 = init_rate_limit_deps


@router.get("/agents/{agent_id}/rate-limit")
@requires(Permission.CONFIG_READ)
async def get_rate_limit(
    agent_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Get current rate limit status for an agent."""
    if _token_limiter is None or _storage is None:
        raise HTTPException(status_code=503, detail="Not initialized")
    agent = await _storage.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    status = _token_limiter.get_status(agent_id)
    status["agent_id"] = agent_id
    status["retry_after_seconds"] = _token_limiter.time_until_available(
        agent_id, 1000,
    )
    return status


@router.post("/agents/{agent_id}/rate-limit/report")
@requires(Permission.AGENT_REGISTER)
async def report_token_usage(
    agent_id: str, body: dict,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Agent reports actual token usage after an LLM call."""
    if _token_limiter is None or _storage is None:
        raise HTTPException(status_code=503, detail="Not initialized")
    agent = await _storage.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    tokens_used = body.get("tokens_used", 0)
    accepted = _token_limiter.consume(agent_id, tokens_used)
    status = _token_limiter.get_status(agent_id)
    if not accepted:
        return {
            "agent_id": agent_id, "accepted": False,
            "error": "rate_limited",
            "retry_after_seconds": _token_limiter.time_until_available(
                agent_id, tokens_used),
        }
    return {
        "agent_id": agent_id, "accepted": True,
        "tokens_remaining": status["tokens_available"],
        "usage_ratio": status["usage_ratio"],
    }


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
