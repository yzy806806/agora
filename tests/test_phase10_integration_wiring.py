"""Tests for Phase 10.4a: Integration Wiring.

Removed: plugins_enabled/plugins_disabled (plugin system removed).
"""
from __future__ import annotations

import os
import pytest

from agora.coordinator.config import Settings
from agora.coordinator.task_exec import execute_task_graph
from agora.coordinator.task_models import TaskGraph, TaskNode, TaskStatus


class TestPhase10Config:
    """Phase 10 config fields exist with backward-compatible defaults."""

    def test_rbac_enforce_default_false(self):
        s = Settings()
        assert s.rbac_enforce is False

    def test_jwt_secret_default_empty(self):
        s = Settings()
        assert s.jwt_secret == ""

    def test_parallel_mode_default_auto(self):
        s = Settings()
        assert s.parallel_mode == "auto"

    def test_rbac_enforce_from_env(self, monkeypatch):
        monkeypatch.setenv("AGORA_RBAC_ENFORCE", "true")
        s = Settings()
        assert s.rbac_enforce is True

    def test_jwt_secret_from_env(self, monkeypatch):
        monkeypatch.setenv("AGORA_JWT_SECRET", "my-secret")
        s = Settings()
        assert s.jwt_secret == "my-secret"

    def test_parallel_mode_from_env(self, monkeypatch):
        monkeypatch.setenv("AGORA_PARALLEL_MODE", "sequential")
        s = Settings()
        assert s.parallel_mode == "sequential"
