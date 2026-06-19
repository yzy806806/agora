"""Tests for TokenRateLimiter (Phase 9.4)."""
import pytest

from agora.coordinator.rate_limiter import TokenRateLimiter


class TestTokenRateLimiter:
    def setup_method(self):
        self.limiter = TokenRateLimiter()

    def test_configure_creates_bucket(self):
        self.limiter.configure("a1", tpm_limit=10000, burst_factor=1.5)
        status = self.limiter.get_status("a1")
        assert status["tpm_limit"] == 10000
        assert status["tpm_burst_factor"] == 1.5

    def test_consume_allowed(self):
        self.limiter.configure("a1", tpm_limit=10000)
        assert self.limiter.consume("a1", 5000) is True

    def test_consume_no_limit(self):
        # No bucket configured → always allow
        assert self.limiter.consume("unknown", 9999) is True

    def test_consume_rate_limited(self):
        self.limiter.configure("a1", tpm_limit=100, burst_factor=1.0)
        self.limiter.consume("a1", 100)
        # Should be limited now (used full capacity)
        assert self.limiter.consume("a1", 1) is False

    def test_remove(self):
        self.limiter.configure("a1", tpm_limit=10000)
        self.limiter.remove("a1")
        status = self.limiter.get_status("a1")
        assert status["tpm_limit"] == 0

    def test_get_status_no_bucket(self):
        status = self.limiter.get_status("unknown")
        assert status["is_limited"] is False
        assert status["usage_ratio"] == 0.0

    def test_tpm_limit_zero_means_unlimited(self):
        self.limiter.configure("a1", tpm_limit=0)
        # No bucket created → allow all
        assert self.limiter.consume("a1", 99999) is True
        status = self.limiter.get_status("a1")
        assert status["tpm_limit"] == 0

    def test_reconfigure_preserves_tokens(self):
        self.limiter.configure("a1", tpm_limit=10000)
        self.limiter.consume("a1", 5000)
        # Reconfigure with higher limit
        self.limiter.configure("a1", tpm_limit=20000)
        status = self.limiter.get_status("a1")
        assert status["tpm_limit"] == 20000

    def test_time_until_available(self):
        self.limiter.configure("a1", tpm_limit=100, burst_factor=1.0)
        self.limiter.consume("a1", 100)
        wait = self.limiter.time_until_available("a1", 50)
        assert wait > 0

    def test_time_until_available_no_bucket(self):
        assert self.limiter.time_until_available("unknown", 100) == 0.0
