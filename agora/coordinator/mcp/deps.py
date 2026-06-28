"""Dependency injection for MCP tools.

Provides access to Storage, TokenManager, and other shared
services from within MCP tool handlers.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_storage = None
_token_mgr = None
_ws_backend = None
_ws_manager = None
_session_map = None


def init_mcp_deps(
    storage, token_mgr=None, ws_manager=None, ws_backend=None,
    session_map=None,
) -> None:
    """Set shared service references. Called from main.py at startup."""
    global _storage, _token_mgr, _ws_backend, _ws_manager, _session_map
    _storage = storage
    _token_mgr = token_mgr
    _ws_backend = ws_backend
    _ws_manager = ws_manager
    _session_map = session_map


def get_storage():
    """Return the Storage instance (raises if not initialized)."""
    if _storage is None:
        raise RuntimeError("MCP deps not initialized: storage")
    return _storage


def get_token_manager():
    """Return the TokenManager instance (may be None)."""
    return _token_mgr


def get_ws_backend():
    """Return the workspace storage backend (may be None)."""
    return _ws_backend


def get_ws_manager():
    """Return the shared WorkspaceManager instance (raises if not initialized)."""
    if _ws_manager is None:
        raise RuntimeError("MCP deps not initialized: ws_manager")
    return _ws_manager


def get_session_map():
    """Return the shared MCPSessionMap instance (raises if not initialized)."""
    if _session_map is None:
        raise RuntimeError("MCP deps not initialized: session_map")
    return _session_map
