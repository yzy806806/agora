"""Type conversion helpers for SQLite → Postgres migration.

Handles: ISO text → TIMESTAMPTZ, JSON text → JSONB, int → BOOLEAN.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def convert_timestamp(value: Any) -> Any:
    """Convert ISO 8601 text to datetime for TIMESTAMPTZ columns."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # Handle empty strings as NULL
        if not value.strip():
            return None
        # Try parsing ISO 8601
        try:
            dt = datetime.fromisoformat(value)
            # Ensure timezone-aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None
    return value


def convert_boolean(value: Any) -> Any:
    """Convert SQLite INTEGER (0/1) to Python bool for BOOLEAN columns."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    return None


def convert_jsonb(value: Any) -> Any:
    """Convert TEXT JSON string to Python object for JSONB columns.

    asyncpg will serialize Python dicts/lists to JSONB automatically.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value  # Return as-is; let Postgres validate
    return value
