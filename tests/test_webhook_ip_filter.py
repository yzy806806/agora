"""Tests for webhook_ip_filter: CIDR-based IP allowlisting."""

import pytest

from agora.coordinator.webhook_ip_filter import is_ip_allowed


class TestIPFilter:
    def test_empty_list_allows_all(self):
        assert is_ip_allowed("1.2.3.4", []) is True
        assert is_ip_allowed("10.0.0.1", []) is True

    def test_exact_ip_match(self):
        assert is_ip_allowed("1.2.3.4", ["1.2.3.4"]) is True
        assert is_ip_allowed("1.2.3.5", ["1.2.3.4"]) is False

    def test_cidr_match(self):
        assert is_ip_allowed("1.2.3.100", ["1.2.3.0/24"]) is True
        assert is_ip_allowed("1.2.4.1", ["1.2.3.0/24"]) is False

    def test_multiple_cidrs(self):
        ips = ["10.0.0.0/8", "192.168.1.0/24"]
        assert is_ip_allowed("10.5.5.5", ips) is True
        assert is_ip_allowed("192.168.1.50", ips) is True
        assert is_ip_allowed("172.16.0.1", ips) is False

    def test_invalid_ip_rejected(self):
        assert is_ip_allowed("not-an-ip", ["1.2.3.0/24"]) is False

    def test_ipv6_support(self):
        assert is_ip_allowed("::1", ["::1/128"]) is True
        assert is_ip_allowed("::2", ["::1/128"]) is False
