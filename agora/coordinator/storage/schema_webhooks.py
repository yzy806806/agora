"""Webhook DDL: SQLite and Postgres schema definitions for webhooks tables.

Extracted from schema.py / schema_postgres.py for Phase 14+ Part D.
"""

# ── SQLite DDL ──────────────────────────────────────────────

WEBHOOKS_SQLITE_DDL = """\
CREATE TABLE IF NOT EXISTS webhooks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    secret_hash TEXT NOT NULL,
    pipeline_template TEXT NOT NULL,
    events TEXT NOT NULL DEFAULT '["push"]',
    enabled INTEGER DEFAULT 1,
    allowed_ips TEXT DEFAULT '[]',
    max_triggers_per_hour INTEGER DEFAULT 60,
    created_at TEXT NOT NULL,
    last_triggered_at TEXT,
    trigger_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_webhooks_project ON webhooks(project_id);

CREATE TABLE IF NOT EXISTS webhook_trigger_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_id TEXT NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
    event TEXT NOT NULL,
    success INTEGER NOT NULL,
    pipeline_id TEXT,
    error TEXT,
    source_ip TEXT,
    triggered_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_webhook_history_webhook
    ON webhook_trigger_history(webhook_id);
"""

# ── Postgres DDL ────────────────────────────────────────────

WEBHOOKS_POSTGRES_DDL = """\
CREATE TABLE IF NOT EXISTS webhooks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    secret_hash TEXT NOT NULL,
    pipeline_template JSONB NOT NULL,
    events JSONB NOT NULL DEFAULT '["push"]',
    enabled BOOLEAN DEFAULT TRUE,
    allowed_ips JSONB DEFAULT '[]',
    max_triggers_per_hour INTEGER DEFAULT 60,
    created_at TIMESTAMPTZ NOT NULL,
    last_triggered_at TIMESTAMPTZ,
    trigger_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_webhooks_project
    ON webhooks(project_id);

CREATE TABLE IF NOT EXISTS webhook_trigger_history (
    id BIGSERIAL PRIMARY KEY,
    webhook_id TEXT NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
    event TEXT NOT NULL,
    success BOOLEAN NOT NULL,
    pipeline_id TEXT,
    error TEXT,
    source_ip TEXT,
    triggered_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_webhook_history_webhook
    ON webhook_trigger_history(webhook_id);
"""

# ── Postgres metadata for migration tooling ─────────────────

WEBHOOKS_POSTGRES_TABLES = ["webhooks", "webhook_trigger_history"]

WEBHOOKS_JSONB_COLUMNS: dict[str, list[str]] = {
    "webhooks": ["pipeline_template", "events", "allowed_ips"],
    "webhook_trigger_history": [],
}

WEBHOOKS_BOOLEAN_COLUMNS: dict[str, list[str]] = {
    "webhooks": ["enabled"],
    "webhook_trigger_history": ["success"],
}

WEBHOOKS_TIMESTAMP_COLUMNS: dict[str, list[str]] = {
    "webhooks": ["created_at", "last_triggered_at"],
    "webhook_trigger_history": ["triggered_at"],
}
