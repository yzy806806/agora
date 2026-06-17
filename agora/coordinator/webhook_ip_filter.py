"""IP allowlisting for webhook triggers with CIDR support.

- Empty allowed_ips list = allow all IPs
- Non-empty list = only IPs matching a CIDR or exact address are allowed
- Returns 403 for blocked IPs
"""

from __future__ import annotations

import ipaddress
import logging

logger = logging.getLogger(__name__)


def is_ip_allowed(source_ip: str, allowed_ips: list[str]) -> bool:
    """Check if a source IP is in the allowed list.

    Args:
        source_ip: The IP address of the incoming request.
        allowed_ips: List of allowed CIDR strings (e.g. ["1.2.3.0/24"]).
                     Empty list means allow all.

    Returns:
        True if allowed, False if blocked.
    """
    if not allowed_ips:
        return True
    try:
        addr = ipaddress.ip_address(source_ip)
    except ValueError:
        logger.warning("Invalid source IP: %s", source_ip)
        return False
    for cidr_str in allowed_ips:
        try:
            network = ipaddress.ip_network(cidr_str, strict=False)
            if addr in network:
                return True
        except ValueError:
            # Treat as exact IP match if not valid CIDR
            if source_ip == cidr_str:
                return True
    return False
