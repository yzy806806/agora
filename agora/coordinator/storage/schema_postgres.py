"""Postgres DDL schema for the Agora Coordinator database.

Maps SQLite types to Postgres equivalents:
- INTEGER PRIMARY KEY AUTOINCREMENT → BIGSERIAL
- TEXT (ISO timestamps) → TIMESTAMPTZ
- INTEGER (boolean) → BOOLEAN
- TEXT (JSON arrays/objects) → JSONB
- BLOB → BYTEA
- REAL → DOUBLE PRECISION
"""

PG_SCHEMA_SQL = """\
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
    allowed_discussion_roles JSONB DEFAULT '["participant"]',
    registration_token TEXT DEFAULT '',
    contact_url TEXT,
    telegram_chat_id TEXT,
    matrix_user_id TEXT
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

CREATE TABLE IF NOT EXISTS assessments (
    id BIGSERIAL PRIMARY KEY,
    motion_id TEXT NOT NULL REFERENCES motions(id) ON DELETE CASCADE,
    round INTEGER,
    result TEXT,
    consensus_level TEXT,
    metrics JSONB,
    rationale TEXT,
    created_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS judgment_records (
    id BIGSERIAL PRIMARY KEY,
    motion_id TEXT NOT NULL REFERENCES motions(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    predicted TEXT NOT NULL,
    actual TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    is_correct BOOLEAN NOT NULL DEFAULT FALSE,
    recorded_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS bootstrap_triggers (
    id BIGSERIAL PRIMARY KEY,
    trigger_type TEXT NOT NULL,
    topic TEXT NOT NULL,
    source TEXT,
    context TEXT,
    priority INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS bootstrap_schedules (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    cron_expression TEXT NOT NULL,
    topic_template TEXT NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    next_run TIMESTAMPTZ,
    last_run TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS bootstrap_approvals (
    id BIGSERIAL PRIMARY KEY,
    motion_id TEXT NOT NULL REFERENCES motions(id) ON DELETE CASCADE,
    decision TEXT NOT NULL,
    rationale TEXT,
    action_items JSONB,
    approval_status TEXT DEFAULT 'pending',
    approved_by TEXT,
    feedback TEXT,
    requested_at TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS bootstrap_agents (
    id BIGSERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    model TEXT,
    capabilities JSONB,
    active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    type TEXT NOT NULL,
    detail TEXT,
    motion_id TEXT,
    agent_id TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS task_graphs (
    id TEXT PRIMARY KEY,
    motion_id TEXT UNIQUE REFERENCES motions(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL,
    parallel_mode TEXT DEFAULT 'auto',
    max_parallel_slots INTEGER DEFAULT 10,
    resource_conflict_policy TEXT DEFAULT 'warn'
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL REFERENCES task_graphs(id) ON DELETE CASCADE,
    motion_id TEXT REFERENCES motions(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    assigned_to TEXT REFERENCES agents(agent_id),
    required_capabilities JSONB,
    depends_on JSONB,
    artifact_paths JSONB,
    workspace_paths JSONB DEFAULT '[]',
    error_message TEXT,
    task_result JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS rate_limit_usage (
    id BIGSERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL,
    window_start DOUBLE PRECISION NOT NULL,
    tokens_consumed INTEGER NOT NULL DEFAULT 0,
    tpm_limit INTEGER NOT NULL,
    last_updated DOUBLE PRECISION NOT NULL,
    UNIQUE(agent_id, window_start)
);

CREATE TABLE IF NOT EXISTS execution_slots (
    id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    started_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS resource_locks (
    id BIGSERIAL PRIMARY KEY,
    resource_path TEXT NOT NULL,
    locked_by TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    waiting_tasks JSONB NOT NULL DEFAULT '[]',
    lock_type TEXT NOT NULL DEFAULT 'write',
    acquired_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS roles (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    permissions_json JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS tokens (
    id BIGSERIAL PRIMARY KEY,
    token_id TEXT NOT NULL UNIQUE,
    token_hash TEXT NOT NULL UNIQUE,
    principal_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'agent',
    scopes JSONB NOT NULL DEFAULT '[]',
    tenant_id TEXT DEFAULT 'default',
    expires_at TIMESTAMPTZ,
    is_revoked BOOLEAN DEFAULT FALSE,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_role TEXT,
    action TEXT NOT NULL,
    resource TEXT,
    details_json JSONB,
    timestamp TIMESTAMPTZ NOT NULL,
    tenant_id TEXT DEFAULT 'default'
);

CREATE TABLE IF NOT EXISTS session_records (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    project_id TEXT NOT NULL DEFAULT 'default',
    session_type TEXT NOT NULL DEFAULT 'task_execution',
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    input_messages JSONB DEFAULT '[]',
    output_messages JSONB DEFAULT '[]',
    tool_calls JSONB DEFAULT '[]',
    errors JSONB DEFAULT '[]',
    outcome TEXT DEFAULT 'success',
    metadata JSONB DEFAULT '{}',
    notes JSONB DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS session_notes (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES session_records(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS project_artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value BYTEA,
    content_type TEXT DEFAULT 'application/octet-stream',
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE(project_id, key)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    idea TEXT NOT NULL,
    motion_id TEXT,
    graph_id TEXT,
    phase TEXT NOT NULL DEFAULT 'discussing',
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    tasks_total INTEGER NOT NULL DEFAULT 0,
    tasks_completed INTEGER NOT NULL DEFAULT 0,
    tasks_failed INTEGER NOT NULL DEFAULT 0,
    review_outcome TEXT,
    release_version TEXT,
    error TEXT,
    failed_phase TEXT
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

CREATE TABLE IF NOT EXISTS file_nodes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    file_type TEXT NOT NULL DEFAULT 'file',
    parent_path TEXT,
    size INTEGER NOT NULL DEFAULT 0,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    checksum_sha256 TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(project_id, path)
);

CREATE TABLE IF NOT EXISTS file_locks (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL REFERENCES file_nodes(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL,
    path TEXT NOT NULL,
    lock_type TEXT NOT NULL DEFAULT 'write',
    held_by TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

-- Phase 14+: Webhook configurations

CREATE TABLE IF NOT EXISTS webhooks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    secret_hash TEXT NOT NULL,
    pipeline_template TEXT NOT NULL,
    events JSONB NOT NULL DEFAULT '["push"]',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    allowed_ips JSONB NOT NULL DEFAULT '[]',
    max_triggers_per_hour INTEGER NOT NULL DEFAULT 60,
    created_at TIMESTAMPTZ NOT NULL,
    last_triggered_at TIMESTAMPTZ,
    trigger_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_webhooks_project ON webhooks(project_id);

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

CREATE INDEX IF NOT EXISTS idx_webhook_history_webhook ON webhook_trigger_history(webhook_id);

-- Standard B-tree indexes

CREATE INDEX IF NOT EXISTS idx_messages_motion ON messages(motion_id);
CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_id);
CREATE INDEX IF NOT EXISTS idx_messages_round ON messages(motion_id, round_num);
CREATE INDEX IF NOT EXISTS idx_votes_motion ON votes(motion_id);
CREATE INDEX IF NOT EXISTS idx_assessments_motion ON assessments(motion_id);
CREATE INDEX IF NOT EXISTS idx_judgment_agent ON judgment_records(agent_id);
CREATE INDEX IF NOT EXISTS idx_judgment_motion ON judgment_records(motion_id);
CREATE INDEX IF NOT EXISTS idx_bootstrap_triggers_status ON bootstrap_triggers(status);
CREATE INDEX IF NOT EXISTS idx_bootstrap_schedules_enabled ON bootstrap_schedules(enabled);
CREATE INDEX IF NOT EXISTS idx_bootstrap_approvals_motion ON bootstrap_approvals(motion_id);
CREATE INDEX IF NOT EXISTS idx_bootstrap_approvals_status ON bootstrap_approvals(approval_status);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_motion ON events(motion_id);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_graph ON tasks(graph_id);
CREATE INDEX IF NOT EXISTS idx_tasks_motion ON tasks(motion_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_rate_limit_agent ON rate_limit_usage(agent_id);
CREATE INDEX IF NOT EXISTS idx_exec_slots_task ON execution_slots(task_id);
CREATE INDEX IF NOT EXISTS idx_exec_slots_agent ON execution_slots(agent_id);
CREATE INDEX IF NOT EXISTS idx_exec_slots_status ON execution_slots(status);
CREATE INDEX IF NOT EXISTS idx_resource_locks_path ON resource_locks(resource_path);
CREATE INDEX IF NOT EXISTS idx_tokens_principal ON tokens(principal_id);
CREATE INDEX IF NOT EXISTS idx_tokens_hash ON tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(tenant_id, actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(tenant_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON session_records(agent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON session_records(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_outcome ON session_records(outcome);
CREATE INDEX IF NOT EXISTS idx_session_notes_session ON session_notes(session_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_project ON project_artifacts(project_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_project ON pipeline_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_phase ON pipeline_runs(phase);
CREATE INDEX IF NOT EXISTS idx_notifications_project ON notifications(project_id);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read);
CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type);
CREATE INDEX IF NOT EXISTS idx_file_nodes_project ON file_nodes(project_id);
CREATE INDEX IF NOT EXISTS idx_file_nodes_parent ON file_nodes(project_id, parent_path);
CREATE INDEX IF NOT EXISTS idx_file_nodes_type ON file_nodes(project_id, file_type);
CREATE INDEX IF NOT EXISTS idx_file_locks_path ON file_locks(project_id, path);
CREATE INDEX IF NOT EXISTS idx_file_locks_holder ON file_locks(held_by);

-- Phase 14+ Part D: Webhook tables

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

CREATE INDEX IF NOT EXISTS idx_webhooks_project ON webhooks(project_id);

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

-- JSONB GIN indexes for queryable fields

CREATE INDEX IF NOT EXISTS idx_agents_capabilities_gin ON agents USING GIN (capabilities);
CREATE INDEX IF NOT EXISTS idx_tasks_required_caps_gin ON tasks USING GIN (required_capabilities);
CREATE INDEX IF NOT EXISTS idx_tasks_depends_on_gin ON tasks USING GIN (depends_on);
"""

# Ordered list of all Postgres table names (used by migration tool)
POSTGRES_TABLES = [
    "agents",
    "motions",
    "messages",
    "votes",
    "assessments",
    "judgment_records",
    "bootstrap_triggers",
    "bootstrap_schedules",
    "bootstrap_approvals",
    "bootstrap_agents",
    "events",
    "task_graphs",
    "tasks",
    "rate_limit_usage",
    "execution_slots",
    "resource_locks",
    "roles",
    "tokens",
    "audit_log",
    "session_records",
    "session_notes",
    "project_artifacts",
    "pipeline_runs",
    "notifications",
    "file_nodes",
    "file_locks",
    "webhooks",
    "webhook_trigger_history",
]

# Columns that store JSONB in Postgres (were TEXT in SQLite)
# Used by migration tool for type conversion
JSONB_COLUMNS: dict[str, list[str]] = {
    "agents": [
        "capabilities", "active_tasks", "allowed_discussion_roles",
    ],
    "motions": ["action_items", "assessment_config", "focus_areas"],
    "votes": ["vote_data"],
    "assessments": ["metrics"],
    "bootstrap_approvals": ["action_items"],
    "bootstrap_agents": ["capabilities"],
    "tasks": [
        "required_capabilities", "depends_on",
        "artifact_paths", "workspace_paths",
    ],
    "resource_locks": ["waiting_tasks"],
    "roles": ["permissions_json"],
    "tokens": ["scopes"],
    "audit_log": ["details_json"],
    "session_records": [
        "input_messages", "output_messages",
        "tool_calls", "errors", "metadata", "notes",
    ],
    "webhooks": ["pipeline_template", "events", "allowed_ips"],
}

# Columns that are BOOLEAN in Postgres (were INTEGER 0/1 in SQLite)
BOOLEAN_COLUMNS: dict[str, list[str]] = {
    "agents": ["is_online", "is_approved"],
    "motions": ["smart_mode", "early_vote_triggered"],
    "judgment_records": ["is_correct"],
    "bootstrap_schedules": ["enabled"],
    "bootstrap_agents": ["active"],
    "tokens": ["is_revoked"],
    "notifications": ["read"],
    "webhooks": ["enabled"],
    "webhook_trigger_history": ["success"],
}

# Columns that are TIMESTAMPTZ in Postgres (were TEXT ISO strings in SQLite)
TIMESTAMP_COLUMNS: dict[str, list[str]] = {
    "agents": ["registered_at", "last_seen_at"],
    "motions": ["created_at", "updated_at", "closed_at"],
    "messages": ["timestamp"],
    "votes": ["timestamp"],
    "assessments": ["created_at"],
    "judgment_records": ["recorded_at"],
    "bootstrap_triggers": ["created_at", "processed_at"],
    "bootstrap_schedules": ["next_run", "last_run"],
    "bootstrap_approvals": ["requested_at", "processed_at"],
    "events": ["created_at"],
    "task_graphs": ["created_at"],
    "tasks": ["created_at", "started_at", "completed_at"],
    "execution_slots": ["started_at"],
    "resource_locks": ["acquired_at"],
    "roles": ["created_at"],
    "tokens": ["expires_at", "revoked_at", "created_at"],
    "audit_log": ["timestamp"],
    "session_records": ["started_at", "ended_at"],
    "session_notes": ["created_at"],
    "project_artifacts": ["created_at", "updated_at"],
    "pipeline_runs": ["started_at", "completed_at"],
    "notifications": ["created_at"],
    "file_nodes": ["created_at", "updated_at"],
    "file_locks": ["acquired_at", "expires_at"],
    "webhooks": ["created_at", "last_triggered_at"],
    "webhook_trigger_history": ["triggered_at"],
}
