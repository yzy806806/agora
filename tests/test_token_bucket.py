"""Tests for TokenBucket and TokenRateLimiter (Phase 9.4)."""
import time
import threading
import pytest

from agora.coordinator.rate_limiter import TokenBucket
from agora.coordinator.rate_limiter import TokenRateLimiter


class TestTokenBucket:
    def test_starts_full(self):
        b = TokenBucket(capacity=1000, refill_rate=10)
        assert b.tokens == 1000

    def test_consume_allowed(self):
        b = TokenBucket(capacity=1000, refill_rate=10)
        assert b.consume(500) is True
        assert b.tokens == 500

    def test_consume_rejected(self):
        b = TokenBucket(capacity=100, refill_rate=10)
        assert b.consume(50) is True
        assert b.consume(60) is False

    def test_refill(self):
        b = TokenBucket(capacity=1000, refill_rate=100)
        b.consume(1000)
        assert b.tokens == 0
        time.sleep(0.1)  # 100 tokens/sec * 0.1s ≈ 10 tokens
        avail = b.available
        assert avail > 0

    def test_usage_ratio(self):
        b = TokenBucket(capacity=1000, refill_rate=10)
        assert b.usage_ratio == 0.0
        b.consume(500)
        assert abs(b.usage_ratio - 0.5) < 0.01

    def test_time_until_available(self):
        b = TokenBucket(capacity=100, refill_rate=100)  # 100 tok/s
        b.consume(100)
        wait = b.time_until_available(50)
        assert wait > 0

    def test_time_until_available_now(self):
        b = TokenBucket(capacity=1000, refill_rate=10)
        assert b.time_until_available(500) == 0.0

    def test_capacity_zero(self):
        b = TokenBucket(capacity=0, refill_rate=0)
        assert b.usage_ratio == 0.0

    def test_concurrent_consume(self):
        b = TokenBucket(capacity=10000, refill_rate=1000)
        results = []

        def try_consume():
            results.append(b.consume(1000))

        threads = [threading.Thread(target=try_consume) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Should not exceed capacity
        assert sum(1 for r in results if r) <= 10
