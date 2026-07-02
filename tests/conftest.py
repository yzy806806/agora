"""Pytest configuration and shared fixtures for Agora tests."""
from __future__ import annotations

import sys
import tempfile
import os
from pathlib import Path

import pytest

# Ensure /root/agora is on sys.path so `from agora.storage import motions` works
_AGORA_ROOT = Path(__file__).resolve().parent.parent
if str(_AGORA_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGORA_ROOT))


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Monkeypatch motions._agora_db_path to return a path in a temp directory.

    This ensures tests never touch the real ~/.hermes/agora/motions.db.
    """
    from agora.storage import motions

    db_path = tmp_path / "motions.db"
    monkeypatch.setattr(motions, "_agora_db_path", lambda: db_path)
    return db_path


@pytest.fixture()
def clean_db(temp_db):
    """Create a fresh DB for each test by ensuring the schema is initialised."""
    from agora.storage import motions

    # _connect() calls _init_schema() which creates tables if they don't exist.
    conn = motions._connect()
    conn.close()
    yield temp_db
