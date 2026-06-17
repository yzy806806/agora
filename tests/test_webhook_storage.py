"""Tests for webhook storage CRUD normalization."""
import json
import pytest

from agora.coordinator.storage.webhook_crud import _normalize_webhook


class TestNormalizeWebhook:
    def test_parses_json_strings(self):
        row = {
            "pipeline_template": '{"idea": "test"}',
            "events": '["push"]',
            "allowed_ips": '["1.2.3.4"]',
            "enabled": 1,
        }
        d = _normalize_webhook(dict(row))
        assert d["pipeline_template"] == {"idea": "test"}
        assert d["events"] == ["push"]
        assert d["allowed_ips"] == ["1.2.3.4"]
        assert d["enabled"] is True

    def test_already_parsed(self):
        row = {
            "pipeline_template": {"idea": "test"},
            "events": ["push"],
            "allowed_ips": [],
            "enabled": 0,
        }
        d = _normalize_webhook(dict(row))
        assert d["pipeline_template"] == {"idea": "test"}
        assert d["enabled"] is False

    def test_invalid_json_raises(self):
        row = {
            "pipeline_template": "not json{{{",
            "events": "[]",
            "allowed_ips": "[]",
            "enabled": 1,
        }
        with pytest.raises(json.JSONDecodeError):
            _normalize_webhook(dict(row))
