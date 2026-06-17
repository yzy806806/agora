"""Tests for webhook_rate_limiter: sliding window per-webhook rate limiting."""

import time

import pytest

from agora.coordinator.webhook_rate_limiter import WebhookRateLimiter


class TestWebhookRateLimiter:
    def test_under_limit_allowed(self):
        limiter = WebhookRateLimiter()
        for _ in range(5):
            assert limiter.check("wh-1", 10) is True

    def test_over_limit_blocked(self):
        limiter = WebhookRateLimiter()
        for _ in range(3):
            assert limiter.check("wh-1", 3) is True
        # 4th should be blocked
        assert limiter.check("wh-1", 3) is False

    def test_different_webhooks_independent(self):
        limiter = WebhookRateLimiter()
        for _ in range(3):
            assert limiter.check("wh-1", 3) is True
        # wh-2 has its own quota
        assert limiter.check("wh-2", 3) is True

    def test_remaining_quota(self):
        limiter = WebhookRateLimiter()
        limiter.check("wh-1", 10)
        limiter.check("wh-1", 10)
        assert limiter.remaining("wh-1", 10) == 8

    def test_reset_clears_counters(self):
        limiter = WebhookRateLimiter()
        for _ in range(3):
            limiter.check("wh-1", 3)
        limiter.reset("wh-1")
        assert limiter.remaining("wh-1", 3) == 3

    def test_default_limit(self):
        limiter = WebhookRateLimiter()
        # Should allow up to 60 (default) per hour
        for _ in range(60):
            assert limiter.check("wh-1", 60) is True
        assert limiter.check("wh-1", 60) is False
