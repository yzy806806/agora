"""Webhook HMAC-SHA256 signature verification + replay attack prevention.

Follows GitHub-compatible pattern:
    X-Agora-Signature-256: sha256=<hex-encoded HMAC>

Also validates X-Agora-Timestamp to prevent replay attacks
within a configurable time window (default 5 minutes).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Default replay-attack prevention window in seconds
DEFAULT_TIMESTAMP_TOLERANCE = 300  # 5 minutes


@dataclass
class VerifyResult:
    """Result of signature + timestamp verification."""
    valid: bool
    reason: str = ""


def compute_signature(secret: str, body: bytes) -> str:
    """Compute HMAC-SHA256 signature over *body* with *secret*.

    Returns the ``sha256=<hex>`` string suitable for the
    ``X-Agora-Signature-256`` header.
    """
    mac = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return f"sha256={mac}"


def verify_signature(
    secret: str,
    body: bytes,
    signature: str,
) -> bool:
    """Verify *signature* matches HMAC-SHA256(secret, body).

    Uses ``hmac.compare_digest`` for constant-time comparison
    to prevent timing attacks.
    """
    expected = compute_signature(secret, body)
    return hmac.compare_digest(expected, signature)


def verify_timestamp(
    timestamp_str: str,
    tolerance: int = DEFAULT_TIMESTAMP_TOLERANCE,
    now: float | None = None,
) -> bool:
    """Return True if *timestamp_str* is within *tolerance* seconds of now.

    *timestamp_str* must be a UNIX epoch string (integer seconds).
    """
    try:
        ts = int(timestamp_str)
    except (ValueError, TypeError):
        return False
    current = now if now is not None else time.time()
    return abs(current - ts) <= tolerance


def verify_webhook_request(
    secret: str,
    body: bytes,
    signature: str,
    timestamp_str: str,
    tolerance: int = DEFAULT_TIMESTAMP_TOLERANCE,
    now: float | None = None,
) -> VerifyResult:
    """Full verification: HMAC signature + timestamp replay check."""
    if not verify_timestamp(timestamp_str, tolerance, now):
        return VerifyResult(
            valid=False, reason="Timestamp outside tolerance window"
        )
    if not verify_signature(secret, body, signature):
        return VerifyResult(valid=False, reason="Invalid signature")
    return VerifyResult(valid=True)
