"""Tests for agora.utils utility functions."""
from __future__ import annotations

import yaml
from pathlib import Path

from agora.utils import (
    safe_name,
    now_iso,
    parse_json_response,
    ensure_in_place_compression,
)


def test_safe_name():
    """safe_name replaces '/' with '-' and ' ' with '_'."""
    assert safe_name("test/name with spaces") == "test-name_with_spaces"


def test_now_iso():
    """now_iso returns an ISO-formatted string containing 'T'."""
    result = now_iso()
    assert isinstance(result, str)
    assert "T" in result


def test_parse_json_response():
    """parse_json_response handles plain JSON, non-JSON, and fenced JSON."""
    # Plain JSON object
    result = parse_json_response('{"action": "continue"}')
    assert result is not None
    assert result["action"] == "continue"

    # Non-JSON text → None
    assert parse_json_response("not json") is None

    # Markdown-fenced JSON → parsed dict
    result = parse_json_response('```json\n{"x": 1}\n```')
    assert result is not None
    assert result["x"] == 1


def test_ensure_in_place_compression(tmp_path):
    """ensure_in_place_compression adds compression.in_place: true to a config."""
    config_path = tmp_path / "config.yaml"

    # Write a config without a compression section
    config_path.write_text("model:\n  default: gpt-4\n")

    ensure_in_place_compression(config_path)

    # Read back and verify
    with open(config_path) as f:
        config = yaml.safe_load(f)

    assert "compression" in config
    assert config["compression"].get("in_place") is True
