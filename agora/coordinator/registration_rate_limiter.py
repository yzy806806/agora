"""IP-based rate limiter for agent self-registration (Phase 15.C.5).

Sliding window: tracks registration attempts per IP address.
Default: 3 requests per minute per IP.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class _Window:
    """Sliding window bucket for a single IP."""
    timestamps: list[float] = field(default_factory=list)


class RegistrationRateLimiter:
    """Simple in-memory sliding-window rate limiter per IP."""

    def __init__(
        self,
        max_requests: int = 3,
        window_seconds: int = 60,
    ) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._buckets: dict[str, _Window] = defaultdict(_Window)

    def is_allowed(self, ip: str) -> bool:
        """Return True if the IP is within rate limits."""
        now = time.monotonic()
        bucket = self._buckets[ip]
        cutoff = now - self._window
        # Prune old entries
        bucket.timestamps = [
            t for t in bucket.timestamps if t > cutoff
        ]
        if len(bucket.timestamps) >= self._max:
            return False
        bucket.timestamps.append(now)
        return True

    def reset(self, ip: str | None = None) -> None:
        """Clear rate limit state for an IP (or all IPs)."""
        if ip is None:
            self._buckets.clear()
        else:
            self._buckets.pop(ip, None)
