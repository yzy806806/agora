"""Per-webhook sliding window rate limiter.

Uses an in-memory sliding window counter (1-hour window).
Upgrade to Redis-backed later for multi-instance coordination.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

# Default: 60 triggers per hour per webhook (matches design doc D.6)
DEFAULT_MAX_TRIGGERS_PER_HOUR = 60
WINDOW_SECONDS = 3600  # 1 hour


class WebhookRateLimiter:
    """In-memory sliding window rate limiter for webhook triggers."""

    def __init__(self) -> None:
        # {webhook_id: [timestamp, ...]}
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, webhook_id: str, limit: int) -> bool:
        """Check if a trigger is allowed for the given webhook.

        Args:
            webhook_id: The webhook identifier.
            limit: Max triggers per hour for this webhook.

        Returns:
            True if allowed, False if rate exceeded.
        """
        now = time.time()
        cutoff = now - WINDOW_SECONDS
        # Prune old entries
        timestamps = [t for t in self._windows[webhook_id] if t > cutoff]
        self._windows[webhook_id] = timestamps
        if len(timestamps) >= limit:
            logger.debug(
                "Rate limit exceeded for webhook %s: %d/%d",
                webhook_id, len(timestamps), limit,
            )
            return False
        timestamps.append(now)
        return True

    def remaining(self, webhook_id: str, limit: int) -> int:
        """Return remaining trigger quota for the current window."""
        now = time.time()
        cutoff = now - WINDOW_SECONDS
        timestamps = [t for t in self._windows[webhook_id] if t > cutoff]
        self._windows[webhook_id] = timestamps
        return max(0, limit - len(timestamps))

    def reset(self, webhook_id: str) -> None:
        """Reset rate limit counters for a webhook."""
        self._windows.pop(webhook_id, None)
