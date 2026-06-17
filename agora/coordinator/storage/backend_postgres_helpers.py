"""Helpers for PostgresBackend: record-to-dict conversion."""

from __future__ import annotations

from typing import Any


def record_to_dict(record: Any) -> dict:
    """Convert an asyncpg Record to a plain dict.

    asyncpg Record objects behave like namedtuples but are not dicts.
    This helper normalizes them for Storage facade consumption.
    """
    if record is None:
        return {}
    return dict(record)


def records_to_dicts(records: list[Any]) -> list[dict]:
    """Convert a list of asyncpg Records to list of dicts."""
    return [dict(r) for r in records]
