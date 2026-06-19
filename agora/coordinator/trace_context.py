"""Simple trace context propagation (replaces observability.trace).

Provides context-variable based trace_id propagation across
REST API (X-Trace-Id header) and WebSocket messages.
"""
from __future__ import annotations

from contextvars import ContextVar

_trace_var: ContextVar[str] = ContextVar("trace_id", default="")


def get_trace_id() -> str:
    """Get the current trace_id from context, or empty string."""
    return _trace_var.get()


def set_trace_id(trace_id: str) -> None:
    """Set the current trace_id in context."""
    _trace_var.set(trace_id)
