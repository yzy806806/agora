"""Rate limiting: sliding window (speak/vote) + token bucket (TPM)."""
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field

from .input_validation import ValidationConfig


class RateLimiter:
    """Per-agent rate limiting with 1-minute sliding window."""

    def __init__(self, config: ValidationConfig | None = None):
        self.config = config or ValidationConfig()
        self._counts: dict[str, dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._limits: dict[str, int] = {
            "speak": self.config.rate_limit_speak,
            "vote": self.config.rate_limit_vote,
        }

    def _window(self) -> float:
        return time.time() - 60.0

    def check_rate(self, agent_id: str, action: str) -> bool:
        """Return True if action allowed, False if rate exceeded."""
        limit = self._limits.get(action)
        if limit is None:
            return True
        cutoff = self._window()
        timestamps = [t for t in self._counts[agent_id][action] if t > cutoff]
        self._counts[agent_id][action] = timestamps
        if len(timestamps) >= limit:
            return False
        timestamps.append(time.time())
        return True

    def get_remaining(self, agent_id: str, action: str) -> int:
        """Return remaining quota for action in current window."""
        limit = self._limits.get(action, 0)
        cutoff = self._window()
        timestamps = [t for t in self._counts[agent_id][action] if t > cutoff]
        self._counts[agent_id][action] = timestamps
        return max(0, limit - len(timestamps))

    def reset(self, agent_id: str) -> None:
        """Reset all rate limit counters for an agent."""
        self._counts.pop(agent_id, None)


@dataclass
class TokenBucket:
    """Thread-safe token bucket for TPM rate limiting."""

    capacity: float
    refill_rate: float  # tokens per second
    tokens: float = 0.0
    last_refill: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        self.tokens = self.capacity
        self.last_refill = time.monotonic()

    def consume(self, count: int) -> bool:
        """Try to consume tokens. Returns True if allowed."""
        with self._lock:
            self._refill()
            if self.tokens >= count:
                self.tokens -= count
                return True
            return False

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    @property
    def available(self) -> float:
        """Current available tokens (triggers refill)."""
        with self._lock:
            self._refill()
            return self.tokens

    @property
    def usage_ratio(self) -> float:
        """0.0 (full) to 1.0 (empty)."""
        if self.capacity <= 0:
            return 0.0
        return 1.0 - (self.available / self.capacity)

    def time_until_available(self, needed: int) -> float:
        """Seconds until needed tokens become available."""
        avail = self.available
        if avail >= needed:
            return 0.0
        if self.refill_rate <= 0:
            return float("inf")
        return (needed - avail) / self.refill_rate


class TokenRateLimiter:
    """Per-agent TPM token bucket tracking."""

    def __init__(self):
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def configure(
        self, agent_id: str, tpm_limit: int, burst_factor: float = 1.5,
    ) -> None:
        """Create or reconfigure a bucket for an agent."""
        if tpm_limit <= 0:
            self.remove(agent_id)
            return
        capacity = tpm_limit * burst_factor
        refill_rate = tpm_limit / 60.0
        with self._lock:
            existing = self._buckets.get(agent_id)
            if existing:
                existing.capacity = capacity
                existing.refill_rate = refill_rate
            else:
                self._buckets[agent_id] = TokenBucket(
                    capacity=capacity, refill_rate=refill_rate,
                )

    def remove(self, agent_id: str) -> None:
        """Remove bucket when agent deregisters."""
        with self._lock:
            self._buckets.pop(agent_id, None)

    def consume(self, agent_id: str, tokens: int) -> bool:
        """Try to consume tokens. Returns False if rate limited."""
        bucket = self._buckets.get(agent_id)
        if bucket is None:
            return True
        return bucket.consume(tokens)

    def get_status(self, agent_id: str) -> dict:
        """Get rate limit status for an agent."""
        bucket = self._buckets.get(agent_id)
        if bucket is None:
            return {
                "tpm_limit": 0, "tpm_burst_factor": 1.0,
                "tokens_available": 0, "tokens_used_this_window": 0,
                "usage_ratio": 0.0, "is_limited": False,
            }
        tpm = int(bucket.refill_rate * 60)
        return {
            "tpm_limit": tpm,
            "tpm_burst_factor": round(bucket.capacity / tpm, 2) if tpm > 0 else 1.0,
            "tokens_available": int(bucket.available),
            "tokens_used_this_window": int(bucket.capacity - bucket.available),
            "usage_ratio": round(bucket.usage_ratio, 4),
            "is_limited": bucket.available <= 0,
        }

    def time_until_available(self, agent_id: str, needed: int) -> float:
        """Seconds until needed tokens become available."""
        bucket = self._buckets.get(agent_id)
        if bucket is None:
            return 0.0
        return bucket.time_until_available(needed)
