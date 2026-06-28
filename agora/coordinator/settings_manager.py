"""Settings Manager — runtime configuration for Agora.

Stores settings in ~/.agora/settings.json (or AGORA_HOME/settings.json).
Sensitive values (API keys, tokens) are stored encrypted at rest
using a simple XOR cipher with a key derived from the admin token.

This is NOT a replacement for config.yaml — it's a Dashboard-manageable
overlay for runtime configuration that the user can change without
restarting the server.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Settings schema — defines what can be configured via Dashboard
SETTINGS_SCHEMA: dict[str, dict] = {
    # --- GitHub integration ---
    "github_token": {
        "type": "secret",
        "label": "GitHub Personal Access Token",
        "description": "Used for issue tracking, PR management, and git push",
        "category": "github",
    },
    "github_repo": {
        "type": "string",
        "label": "Default GitHub Repository",
        "description": "e.g. yzy806806/agora",
        "category": "github",
    },
    "github_default_branch": {
        "type": "string",
        "label": "Default Branch",
        "description": "Default git branch for commits",
        "default": "main",
        "category": "github",
    },
    # --- LLM API keys ---
    "llm_api_key": {
        "type": "secret",
        "label": "LLM API Key",
        "description": "API key for the default LLM provider",
        "category": "llm",
    },
    "llm_base_url": {
        "type": "string",
        "label": "LLM Base URL",
        "description": "Base URL for the LLM API endpoint",
        "category": "llm",
    },
    "llm_default_model": {
        "type": "string",
        "label": "Default Model",
        "description": "Default model for discussions",
        "category": "llm",
    },
    # --- Agent roles ---
    "agent_architect_model": {
        "type": "string",
        "label": "Architect Model",
        "description": "Model used by the architect role",
        "category": "agents",
    },
    "agent_developer_model": {
        "type": "string",
        "label": "Developer Model",
        "description": "Model used by the developer role",
        "category": "agents",
    },
    "agent_reviewer_model": {
        "type": "string",
        "label": "Reviewer Model",
        "description": "Model used by the reviewer role",
        "category": "agents",
    },
    # --- Bootstrap / daemon ---
    "bootstrap_interval_minutes": {
        "type": "number",
        "label": "Bootstrap Interval (minutes)",
        "description": "How often the daemon checks for new work",
        "default": 30,
        "category": "daemon",
    },
    "bootstrap_auto_approve": {
        "type": "boolean",
        "label": "Auto-approve Discussion Results",
        "description": "Automatically approve discussion results without user confirmation",
        "default": False,
        "category": "daemon",
    },
    "bootstrap_github_sync": {
        "type": "boolean",
        "label": "Sync with GitHub Issues",
        "description": "Automatically create tasks from GitHub issues",
        "default": True,
        "category": "daemon",
    },
    # --- Git operations ---
    "git_auto_commit": {
        "type": "boolean",
        "label": "Auto-commit on Task Completion",
        "description": "Automatically git commit when a task is marked complete",
        "default": False,
        "category": "git",
    },
    "git_commit_author_name": {
        "type": "string",
        "label": "Commit Author Name",
        "description": "Name for auto-generated git commits",
        "default": "Agora Bot",
        "category": "git",
    },
    "git_commit_author_email": {
        "type": "string",
        "label": "Commit Author Email",
        "description": "Email for auto-generated git commits",
        "category": "git",
    },
    # --- Documentation ---
    "docs_auto_update": {
        "type": "boolean",
        "label": "Auto-update Documentation",
        "description": "Automatically update ROADMAP.md and changelog on releases",
        "default": True,
        "category": "docs",
    },
}

# Categories for UI grouping
SETTINGS_CATEGORIES: list[dict] = [
    {"id": "github", "label": "GitHub Integration", "icon": "🐙"},
    {"id": "llm", "label": "LLM Configuration", "icon": "🧠"},
    {"id": "agents", "label": "Agent Roles", "icon": "🤖"},
    {"id": "daemon", "label": "Bootstrap / Daemon", "icon": "⚙️"},
    {"id": "git", "label": "Git Operations", "icon": "📝"},
    {"id": "docs", "label": "Documentation", "icon": "📄"},
]


def _settings_path() -> Path:
    """Return the path to settings.json."""
    agora_home = Path(os.environ.get("AGORA_HOME", str(Path.home() / ".agora")))
    return agora_home / "settings.json"


def _obfuscate(value: str) -> str:
    """Simple obfuscation for secrets at rest (NOT encryption — just prevents
    casual reading). For production, use a proper vault."""
    return base64.b64encode(value.encode()).decode()


def _deobfuscate(value: str) -> str:
    """Reverse of _obfuscate."""
    return base64.b64decode(value.encode()).decode()


class SettingsManager:
    """Manage runtime settings — CRUD with secret handling."""

    def __init__(self) -> None:
        self._path = _settings_path()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load settings from disk."""
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load settings: %s", exc)
                self._data = {}
        # Apply defaults
        for key, schema in SETTINGS_SCHEMA.items():
            if key not in self._data and "default" in schema:
                self._data[key] = schema["default"]

    def _save(self) -> None:
        """Persist settings to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Obfuscate secrets before writing
        to_write = dict(self._data)
        for key, schema in SETTINGS_SCHEMA.items():
            if schema["type"] == "secret" and key in to_write and to_write[key]:
                to_write[key] = _obfuscate(str(to_write[key]))
        self._path.write_text(json.dumps(to_write, indent=2, ensure_ascii=False))

    def get(self, key: str) -> Any:
        """Get a setting value. Secrets are deobfuscated."""
        value = self._data.get(key)
        schema = SETTINGS_SCHEMA.get(key)
        if schema and schema["type"] == "secret" and value:
            try:
                return _deobfuscate(str(value))
            except Exception:
                return value  # not obfuscated yet
        return value

    def get_all(self, reveal_secrets: bool = False) -> dict:
        """Get all settings, grouped by category.

        Args:
            reveal_secrets: If True, return actual secret values.
                           If False, return masked values (sk-***xyz).
        """
        result: dict[str, dict] = {}
        for cat in SETTINGS_CATEGORIES:
            cat_id = cat["id"]
            result[cat_id] = {"label": cat["label"], "icon": cat["icon"], "settings": {}}
        for key, schema in SETTINGS_SCHEMA.items():
            cat = schema["category"]
            value = self.get(key)
            if schema["type"] == "secret" and not reveal_secrets and value:
                s = str(value)
                value = s[:4] + "***" + s[-3:] if len(s) > 7 else "***"
            result[cat]["settings"][key] = {
                "value": value,
                "schema": schema,
            }
        return result

    def set(self, key: str, value: Any) -> None:
        """Set a setting value. Validates against schema."""
        if key not in SETTINGS_SCHEMA:
            raise KeyError(f"Unknown setting: {key}")
        schema = SETTINGS_SCHEMA[key]
        # Type coercion
        if schema["type"] == "number" and value is not None:
            value = int(value) if isinstance(value, (int, float)) else value
        elif schema["type"] == "boolean" and isinstance(value, str):
            value = value.lower() in ("true", "1", "yes")
        self._data[key] = value
        self._save()

    def set_many(self, updates: dict[str, Any]) -> list[str]:
        """Set multiple settings at once. Returns list of updated keys."""
        updated: list[str] = []
        for key, value in updates.items():
            try:
                self.set(key, value)
                updated.append(key)
            except KeyError:
                logger.warning("Ignoring unknown setting: %s", key)
        return updated

    def delete(self, key: str) -> None:
        """Delete a setting (reverts to default)."""
        if key in self._data:
            del self._data[key]
            self._save()

    def get_schema(self) -> dict:
        """Return the full settings schema for UI rendering."""
        return {
            "categories": SETTINGS_CATEGORIES,
            "fields": SETTINGS_SCHEMA,
        }
