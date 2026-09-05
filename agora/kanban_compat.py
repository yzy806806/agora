"""Compatibility bridge for the Hermes September 2026 module decomposition (PR #102117).

`hermes_cli.kanban_db` was split into focused submodules (kanban_db_connect,
kanban_db_dispatch, ...). Hermes kept a temporary compat layer that re-exports
moved names from their old paths, but that layer is scheduled for removal on
2026-09-14. After removal, `kanban_db.connect` (which Agora uses in 19 call
sites) would raise AttributeError and the plugin would fail to load.

This module resolves kanban_db symbols against the new submodule locations
first, falling back to the legacy module attribute for older Hermes versions
(< the decomposition), so a single Agora build works across both layouts.

Usage — replace::

    from hermes_cli import kanban_db
    conn = kanban_db.connect()

with::

    from agora.kanban_compat import kanban_db
    conn = kanban_db.connect()

The returned object is a namespace-like bridge exposing every symbol from the
real kanban_db package plus explicit overrides for names that moved to
submodules.
"""
from __future__ import annotations

import importlib
import logging
import types

logger = logging.getLogger(__name__)

# symbol -> candidate new-location modules, in preference order
_MOVED: dict[str, list[str]] = {
    "connect": ["hermes_cli.kanban_db_connect"],
}

_OVERRIDDEN: set[str] = set()


def _build_bridge() -> types.ModuleType:
    global _OVERRIDDEN
    real = importlib.import_module("hermes_cli.kanban_db")

    bridge = types.ModuleType("agora.kanban_compat.kanban_db")
    bridge.__doc__ = "Compatibility bridge over hermes_cli.kanban_db (see agora.kanban_compat)."

    # Proxy attribute access to the real module for anything not resolved here.
    class _Bridge(types.ModuleType):
        def __getattr__(self, name: str):  # noqa: D105
            return getattr(real, name)

    bridge.__class__ = _Bridge

    # Copy the real module's public surface eagerly so dir() and Starlette-ish
    # introspection behave sensibly.
    for name in dir(real):
        if not name.startswith("__"):
            try:
                setattr(bridge, name, getattr(real, name))
            except Exception:  # pragma: no cover - defensive
                pass

    # Override the moved symbols with the new-location resolution.
    for symbol, candidates in _MOVED.items():
        resolved = None
        for mod_name in candidates:
            try:
                mod = importlib.import_module(mod_name)
                if hasattr(mod, symbol):
                    resolved = getattr(mod, symbol)
                    break
            except ImportError:
                continue
        if resolved is None:
            # Old Hermes (< decomposition): symbol still lives in kanban_db.
            resolved = getattr(real, symbol, None)
        if resolved is not None:
            setattr(bridge, symbol, resolved)
            _OVERRIDDEN.add(symbol)

    return bridge


kanban_db = _build_bridge()

__all__ = ["kanban_db"]
