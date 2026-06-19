"""Auth router — Phase 11.2a + Phase 15.A: Dashboard user login/logout.

POST /api/v1/auth/login validates username+password against
AGORA_DASHBOARD_USERS env var, returns JWT on success with Set-Cookie.
POST /api/v1/auth/logout clears the dashboard_token cookie.
Returns 501 if AGORA_DASHBOARD_USERS not configured (backward compat).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from .auth_helpers import parse_dashboard_users, verify_password
from .token_manager import TokenManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_token_mgr: Optional[TokenManager] = None

COOKIE_NAME = "dashboard_token"
COOKIE_MAX_AGE = 86400  # 24 hours


def init_auth_deps(token_mgr: TokenManager) -> None:
    """Set TokenManager reference. Called at app startup."""
    global _token_mgr
    _token_mgr = token_mgr


class LoginRequest(BaseModel):
    """Dashboard login request."""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Dashboard login response."""
    token: str
    role: str
    expires_in: int = 3600


def _set_cookie(response: Response, token: str) -> None:
    """Set dashboard_token cookie on response."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


def _clear_cookie(response: Response) -> None:
    """Clear dashboard_token cookie on response."""
    response.set_cookie(
        key=COOKIE_NAME,
        value="",
        max_age=0,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response) -> LoginResponse:
    """Authenticate dashboard user, return JWT with Set-Cookie."""
    if _token_mgr is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    users = parse_dashboard_users()
    if not users:
        raise HTTPException(
            status_code=501,
            detail="Dashboard auth not configured (AGORA_DASHBOARD_USERS)",
        )
    hashed = users.get(request.username)
    if hashed is None or not verify_password(request.password, hashed):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    role = "admin" if request.username == list(users.keys())[0] else "observer"
    token = _token_mgr.create_token(
        agent_id=f"dashboard_user:{request.username}",
        role=role,
        expires_delta=COOKIE_MAX_AGE,
    )
    _set_cookie(response, token)
    return LoginResponse(token=token, role=role, expires_in=COOKIE_MAX_AGE)


@router.post("/logout")
async def logout(response: Response) -> dict:
    """Clear dashboard_token cookie (client should also discard JWT)."""
    _clear_cookie(response)
    return {"status": "logged_out"}
