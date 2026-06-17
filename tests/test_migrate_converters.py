"""Tests for migration type converters and core logic."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from agora.coordinator.storage.migrate_converters import (
    convert_boolean,
    convert_jsonb,
    convert_timestamp,
)
from agora.coordinator.storage.migrate_core import (
    _convert_row,
    read_sqlite_tables,
)


class TestConvertTimestamp:
    def test_iso_string(self) -> None:
        result = convert_timestamp("2024-01-15T10:30:00+00:00")
        assert isinstance(result, datetime)
        assert result.year == 2024

    def test_iso_string_no_tz(self) -> None:
        result = convert_timestamp("2024-01-15T10:30:00")
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    def test_none(self) -> None:
        assert convert_timestamp(None) is None

    def test_empty_string(self) -> None:
        assert convert_timestamp("") is None
        assert convert_timestamp("  ") is None

    def test_already_datetime(self) -> None:
        dt = datetime(2024, 1, 15, tzinfo=timezone.utc)
        assert convert_timestamp(dt) is dt

    def test_invalid_string(self) -> None:
        assert convert_timestamp("not-a-date") is None


class TestConvertBoolean:
    def test_int_one(self) -> None:
        assert convert_boolean(1) is True

    def test_int_zero(self) -> None:
        assert convert_boolean(0) is False

    def test_none(self) -> None:
        assert convert_boolean(None) is None

    def test_already_bool(self) -> None:
        assert convert_boolean(True) is True
        assert convert_boolean(False) is False


class TestConvertJsonb:
    def test_valid_json_list(self) -> None:
        result = convert_jsonb('["a", "b"]')
        assert result == ["a", "b"]

    def test_valid_json_dict(self) -> None:
        result = convert_jsonb('{"key": "val"}')
        assert result == {"key": "val"}

    def test_none(self) -> None:
        assert convert_jsonb(None) is None

    def test_empty_string(self) -> None:
        assert convert_jsonb("") is None

    def test_already_parsed(self) -> None:
        assert convert_jsonb(["x"]) == ["x"]
        assert convert_jsonb({"a": 1}) == {"a": 1}
