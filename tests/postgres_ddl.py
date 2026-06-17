"""Postgres DDL for integration tests.

Mirrors DESIGN-phase14plus.md Part A.4 schema.
Will later be moved to agora/coordinator/storage/schema_postgres.py.
"""

POSTGRES_DDL = """\
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    hermes_endpoint TEXT,
    model TEXT,
    capabilities JSONB DEFAULT '[]',
    role TEXT DEFAULT 'expert',
    registered_at TIMESTAMPTZ NOT NULL,
    is_online BOOLEAN DEFAULT FALSE,
    last_seen_at TIMESTAMPTZ,
    agent_type TEXT DEFAULT 'hermes',
    max_concurrent_tasks INTEGER DEFAULT 2,
    agent_token TEXT DEFAULT '',
    is_approved BOOLEAN DEFAULT FALSE,
    approval_status TEXT DEFAULT 'pending',
    load DOUBLE PRECISION DEFAULT 0.0,
    active_tasks JSONB DEFAULT '[]',
    tpm_limit INTEGER DEFAULT 10000,
    tpm_burst_factor DOUBLE PRECISION DEFAULT 1.5,
    allowed_discussion_roles JSONB DEFAULT '["participant"]'
);

CREATE TABLE IF NOT EXISTS motions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    context TEXT,
    rounds INTEGER NOT NULL DEFAULT 3,
    voting_method TEXT NOT NULL DEFAULT 'simple_majority',
    status TEXT NOT NULL DEFAULT 'draft',
    current_round INTEGER DEFAULT 0,
    decision TEXT,
    rationale TEXT,
    action_items JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    smart_mode BOOLEAN DEFAULT TRUE,
    assessment_config JSONB,
    devils_advocate_count INTEGER DEFAULT 0,
    focus_areas JSONB,
    early_vote_triggered BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    motion_id TEXT NOT NULL REFERENCES motions(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    round_num INTEGER NOT NULL,
    stance TEXT,
    content TEXT NOT NULL,
    evidence TEXT,
    timestamp TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS votes (
    id BIGSERIAL PRIMARY KEY,
    motion_id TEXT NOT NULL REFERENCES motions(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    vote TEXT NOT NULL,
    vote_type TEXT NOT NULL DEFAULT 'binary',
    vote_data JSONB,
    confidence DOUBLE PRECISION,
    reason TEXT,
    timestamp TIMESTAMPTZ NOT NULL,
    UNIQUE(motion_id, agent_id)
);

CREATE TABLE IF NOT EXISTS roles (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    permissions_json JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    graph_id TEXT,
    motion_id TEXT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    assigned_to TEXT REFERENCES agents(agent_id),
    required_capabilities JSONB,
    depends_on JSONB,
    workspace_paths JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    project_id TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'medium',
    created_at TIMESTAMPTZ NOT NULL,
    read BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_agents_capabilities_gin
    ON agents USING GIN (capabilities);
CREATE INDEX IF NOT EXISTS idx_tasks_required_caps_gin
    ON tasks USING GIN (required_capabilities);
CREATE INDEX IF NOT EXISTS idx_tasks_depends_on_gin
    ON tasks USING GIN (depends_on);
"""
