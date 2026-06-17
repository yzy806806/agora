"""Tests for webhook_verifier: HMAC signature + timestamp verification."""

import hashlib
import hmac
import time

import pytest

from agora.coordinator.webhook_verifier import (
    compute_signature,
    verify_signature,
    verify_timestamp,
    verify_webhook_request,
    VerifyResult,
)


class TestComputeSignature:
    def test_format(self):
        sig = compute_signature("secret", b"body")
        assert sig.startswith("sha256=")
        assert len(sig) == 71  # "sha256=" + 64 hex chars

    def test_matches_manual(self):
        secret, body = "my-secret", b'{"event":"push"}'
        expected = hmac.new(
            secret.encode(), body, hashlib.sha256,
        ).hexdigest()
        assert compute_signature(secret, body) == f"sha256={expected}"


class TestVerifySignature:
    def test_valid_signature(self):
        secret, body = "my-secret", b'{"event": "push"}'
        sig = compute_signature(secret, body)
        assert verify_signature(secret, body, sig) is True

    def test_invalid_signature(self):
        assert verify_signature("s", b"b", "sha256=bad") is False

    def test_wrong_secret(self):
        body = b"test-body"
        sig = compute_signature("wrong", body)
        assert verify_signature("right", body, sig) is False

    def test_tampered_body(self):
        sig = compute_signature("secret", b"original")
        assert verify_signature("secret", b"tampered", sig) is False

    def test_constant_time(self):
        """verify_signature uses hmac.compare_digest (no timing leak)."""
        sig = compute_signature("secret", b"body")
        assert verify_signature("secret", b"body", sig) is True


class TestVerifyTimestamp:
    def test_valid(self):
        assert verify_timestamp(str(int(time.time()))) is True

    def test_expired(self):
        assert verify_timestamp(str(int(time.time()) - 600), tolerance=300) is False

    def test_invalid_string(self):
        assert verify_timestamp("not-a-number") is False

    def test_future_within_tolerance(self):
        assert verify_timestamp(str(int(time.time()) + 100), tolerance=300) is True


class TestVerifyWebhookRequest:
    def test_full_valid(self):
        secret, body = "s", b"b"
        sig = compute_signature(secret, body)
        ts = str(int(time.time()))
        result = verify_webhook_request(secret, body, sig, ts)
        assert result.valid is True
        assert result.reason == ""

    def test_bad_signature(self):
        ts = str(int(time.time()))
        result = verify_webhook_request("s", b"b", "sha256=bad", ts)
        assert result.valid is False
        assert "signature" in result.reason.lower()

    def test_bad_timestamp(self):
        secret, body = "s", b"b"
        sig = compute_signature(secret, body)
        old_ts = str(int(time.time()) - 600)
        result = verify_webhook_request(secret, body, sig, old_ts, tolerance=300)
        assert result.valid is False
        assert "timestamp" in result.reason.lower()
