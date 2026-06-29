"""SQL schema definitions for the Agora Coordinator database."""

SCHEMA_VERSION = 24

SCHEMA_SQL = """\
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    hermes_endpoint TEXT,
    model TEXT,
    capabilities TEXT,
    role TEXT DEFAULT 'expert',
    registered_at TEXT NOT NULL,
    is_online INTEGER DEFAULT 0,
    last_seen_at TEXT,
    agent_type TEXT DEFAULT 'hermes',
    max_concurrent_tasks INTEGER DEFAULT 2,
    agent_token TEXT DEFAULT '',
    is_approved INTEGER DEFAULT 0,
    approval_status TEXT DEFAULT 'pending',
    load REAL DEFAULT 0.0,
    active_tasks TEXT DEFAULT '[]',
    tpm_limit INTEGER DEFAULT 10000,
    tpm_burst_factor REAL DEFAULT 1.5,
    allowed_discussion_roles TEXT DEFAULT '["participant"]',
    registration_token TEXT DEFAULT '',
    contact_url TEXT DEFAULT NULL,
    telegram_chat_id TEXT DEFAULT NULL,
    matrix_user_id TEXT DEFAULT NULL
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
    action_items TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT,
    smart_mode INTEGER DEFAULT 1,
    assessment_config TEXT,
    devils_advocate_count INTEGER DEFAULT 0,
    focus_areas TEXT,
    early_vote_triggered INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    motion_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    round_num INTEGER NOT NULL,
    stance TEXT,
    content TEXT NOT NULL,
    evidence TEXT,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (motion_id) REFERENCES motions(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

CREATE TABLE IF NOT EXISTS votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    motion_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    vote TEXT NOT NULL,
    vote_type TEXT NOT NULL DEFAULT 'binary',
    vote_data TEXT,
    confidence REAL,
    reason TEXT,
    timestamp TEXT NOT NULL,
    UNIQUE(motion_id, agent_id),
    FOREIGN KEY (motion_id) REFERENCES motions(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_motion ON messages(motion_id);
CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_id);
CREATE INDEX IF NOT EXISTS idx_messages_round ON messages(motion_id, round_num);
CREATE INDEX IF NOT EXISTS idx_votes_motion ON votes(motion_id);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    motion_id TEXT NOT NULL,
    round INTEGER,
    result TEXT,
    consensus_level TEXT,
    metrics TEXT,
    rationale TEXT,
    created_at TEXT,
    FOREIGN KEY (motion_id) REFERENCES motions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_assessments_motion ON assessments(motion_id);

CREATE TABLE IF NOT EXISTS judgment_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    motion_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    predicted TEXT NOT NULL,
    actual TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    is_correct INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (motion_id) REFERENCES motions(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_judgment_agent ON judgment_records(agent_id);
CREATE INDEX IF NOT EXISTS idx_judgment_motion ON judgment_records(motion_id);

-- Bootstrap tables for self-organizing development

CREATE TABLE IF NOT EXISTS bootstrap_triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_type TEXT NOT NULL,
    topic TEXT NOT NULL,
    source TEXT,
    context TEXT,
    priority INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS bootstrap_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    cron_expression TEXT NOT NULL,
    topic_template TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    next_run TEXT,
    last_run TEXT
);

CREATE TABLE IF NOT EXISTS bootstrap_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    motion_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    rationale TEXT,
    action_items TEXT,
    approval_status TEXT DEFAULT 'pending',
    approved_by TEXT,
    feedback TEXT,
    requested_at TEXT NOT NULL,
    processed_at TEXT,
    FOREIGN KEY (motion_id) REFERENCES motions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bootstrap_agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    model TEXT,
    capabilities TEXT,
    active INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_bootstrap_triggers_status ON bootstrap_triggers(status);
CREATE INDEX IF NOT EXISTS idx_bootstrap_schedules_enabled ON bootstrap_schedules(enabled);
CREATE INDEX IF NOT EXISTS idx_bootstrap_approvals_motion ON bootstrap_approvals(motion_id);
CREATE INDEX IF NOT EXISTS idx_bootstrap_approvals_status ON bootstrap_approvals(approval_status);

-- Phase 8: Dashboard event log

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    detail TEXT,
    motion_id TEXT,
    agent_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_motion ON events(motion_id);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);

-- Phase 9: Task Execution Engine

CREATE TABLE IF NOT EXISTS task_graphs (
    id TEXT PRIMARY KEY,
    motion_id TEXT UNIQUE,
    created_at TEXT NOT NULL,
    parallel_mode TEXT DEFAULT 'auto',
    max_parallel_slots INTEGER DEFAULT 10,
    resource_conflict_policy TEXT DEFAULT 'warn',
    FOREIGN KEY (motion_id) REFERENCES motions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    motion_id TEXT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    assigned_to TEXT,
    required_capabilities TEXT,
    depends_on TEXT,
    artifact_paths TEXT,
    workspace_paths TEXT DEFAULT '[]',
    error_message TEXT,
    task_result TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (graph_id) REFERENCES task_graphs(id) ON DELETE CASCADE,
    FOREIGN KEY (motion_id) REFERENCES motions(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_to) REFERENCES agents(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_graph ON tasks(graph_id);
CREATE INDEX IF NOT EXISTS idx_tasks_motion ON tasks(motion_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to);

-- Phase 9.4: Rate limit usage tracking
CREATE TABLE IF NOT EXISTS rate_limit_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    window_start REAL NOT NULL,
    tokens_consumed INTEGER NOT NULL DEFAULT 0,
    tpm_limit INTEGER NOT NULL,
    last_updated REAL NOT NULL,
    UNIQUE(agent_id, window_start)
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_agent ON rate_limit_usage(agent_id);

-- Phase 10: Parallel execution tables

CREATE TABLE IF NOT EXISTS execution_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_exec_slots_task ON execution_slots(task_id);
CREATE INDEX IF NOT EXISTS idx_exec_slots_agent ON execution_slots(agent_id);
CREATE INDEX IF NOT EXISTS idx_exec_slots_status ON execution_slots(status);

CREATE TABLE IF NOT EXISTS resource_locks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_path TEXT NOT NULL,
    locked_by TEXT NOT NULL,
    waiting_tasks TEXT NOT NULL DEFAULT '[]',
    lock_type TEXT NOT NULL DEFAULT 'write',
    acquired_at TEXT NOT NULL,
    FOREIGN KEY (locked_by) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_resource_locks_path ON resource_locks(resource_path);
CREATE INDEX IF NOT EXISTS idx_rate_limit_agent ON rate_limit_usage(agent_id);

-- Phase 10.2: RBAC tables

CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    permissions_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id TEXT NOT NULL UNIQUE,
    token_hash TEXT NOT NULL UNIQUE,
    principal_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'agent',
    scopes TEXT NOT NULL DEFAULT '[]',
    tenant_id TEXT DEFAULT 'default',
    expires_at TEXT,
    is_revoked INTEGER DEFAULT 0,
    revoked_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_role TEXT,
    action TEXT NOT NULL,
    resource TEXT,
    details_json TEXT,
    timestamp TEXT NOT NULL,
    tenant_id TEXT DEFAULT 'default'
);

CREATE INDEX IF NOT EXISTS idx_tokens_principal ON tokens(principal_id);
CREATE INDEX IF NOT EXISTS idx_tokens_hash ON tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(tenant_id, actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(tenant_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event_type);

-- Phase 12.5: Session persistence for agent self-evolution
CREATE TABLE IF NOT EXISTS session_records (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT 'default',
    session_type TEXT NOT NULL DEFAULT 'task_execution',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    input_messages TEXT DEFAULT '[]',
    output_messages TEXT DEFAULT '[]',
    tool_calls TEXT DEFAULT '[]',
    errors TEXT DEFAULT '[]',
    outcome TEXT DEFAULT 'success',
    metadata TEXT DEFAULT '{}',
    notes TEXT DEFAULT '[]',
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_agent ON session_records(agent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON session_records(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_outcome ON session_records(outcome);

CREATE TABLE IF NOT EXISTS session_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES session_records(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_session_notes_session ON session_notes(session_id);

CREATE TABLE IF NOT EXISTS project_artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value BLOB,
    content_type TEXT DEFAULT 'application/octet-stream',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, key)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_project ON project_artifacts(project_id);

-- Phase 13: Pipeline runs for full-auto dev loop

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    idea TEXT NOT NULL,
    motion_id TEXT,
    graph_id TEXT,
    phase TEXT NOT NULL DEFAULT 'discussing',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    tasks_total INTEGER NOT NULL DEFAULT 0,
    tasks_completed INTEGER NOT NULL DEFAULT 0,
    tasks_failed INTEGER NOT NULL DEFAULT 0,
    review_outcome TEXT,
    release_version TEXT,
    error TEXT,
    failed_phase TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_project ON pipeline_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_phase ON pipeline_runs(phase);

-- Phase 13: Notifications for dashboard enhancement

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    project_id TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'medium',
    created_at TEXT NOT NULL,
    read INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_notifications_project ON notifications(project_id);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read);
CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type);

-- Phase 14+: Webhook configurations

CREATE TABLE IF NOT EXISTS webhooks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    secret_hash TEXT NOT NULL,
    pipeline_template TEXT NOT NULL,
    events TEXT NOT NULL DEFAULT '["push"]',
    enabled INTEGER NOT NULL DEFAULT 1,
    allowed_ips TEXT NOT NULL DEFAULT '[]',
    max_triggers_per_hour INTEGER NOT NULL DEFAULT 60,
    created_at TEXT NOT NULL,
    last_triggered_at TEXT,
    trigger_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0
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

CREATE INDEX IF NOT EXISTS idx_webhook_history_webhook ON webhook_trigger_history(webhook_id);

-- Phase 14: Workspace file_nodes + file_locks

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
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(project_id, path)
);

CREATE INDEX IF NOT EXISTS idx_file_nodes_project ON file_nodes(project_id);
CREATE INDEX IF NOT EXISTS idx_file_nodes_parent ON file_nodes(project_id, parent_path);
CREATE INDEX IF NOT EXISTS idx_file_nodes_type ON file_nodes(project_id, file_type);

CREATE TABLE IF NOT EXISTS file_locks (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    path TEXT NOT NULL,
    lock_type TEXT NOT NULL DEFAULT 'write',
    held_by TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (file_id) REFERENCES file_nodes(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_file_locks_path ON file_locks(project_id, path);
CREATE INDEX IF NOT EXISTS idx_file_locks_holder ON file_locks(held_by);

-- Phase 16.4: MCP session tracking

CREATE TABLE IF NOT EXISTS mcp_sessions (
    mcp_session_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    connected_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    transport_type TEXT DEFAULT 'streamable-http'
);

CREATE INDEX IF NOT EXISTS idx_mcp_sessions_agent ON mcp_sessions(agent_id);

-- Phase 19: Pending notifications queue (for offline agent wakeup)

CREATE TABLE IF NOT EXISTS pending_notifications (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    notification_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    acked_at TEXT,
    expires_at TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_pend_notif_agent ON pending_notifications(agent_id, status);
CREATE INDEX IF NOT EXISTS idx_pend_notif_status ON pending_notifications(status);
"""
MIGRATION_6_TO_7 = [
    "ALTER TABLE agents ADD COLUMN agent_type TEXT DEFAULT 'hermes';",
    "ALTER TABLE agents ADD COLUMN max_concurrent_tasks INTEGER DEFAULT 2;",
    "ALTER TABLE agents ADD COLUMN agent_token TEXT DEFAULT '';",
    "ALTER TABLE agents ADD COLUMN is_approved INTEGER DEFAULT 0;",
    "ALTER TABLE agents ADD COLUMN approval_status TEXT DEFAULT 'pending';",
    "ALTER TABLE agents ADD COLUMN load REAL DEFAULT 0.0;",
    "ALTER TABLE agents ADD COLUMN active_tasks TEXT DEFAULT '[]';",
]

# Phase 9.4: Rate limit usage table + agent tpm columns (schema version 7 → 8)
MIGRATION_7_TO_8 = [
    """CREATE TABLE IF NOT EXISTS rate_limit_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    window_start REAL NOT NULL,
    tokens_consumed INTEGER NOT NULL DEFAULT 0,
    tpm_limit INTEGER NOT NULL,
    last_updated REAL NOT NULL,
    UNIQUE(agent_id, window_start)
);""",
    "CREATE INDEX IF NOT EXISTS idx_rate_limit_agent ON rate_limit_usage(agent_id);",
    "ALTER TABLE agents ADD COLUMN tpm_limit INTEGER DEFAULT 10000;",
    "ALTER TABLE agents ADD COLUMN tpm_burst_factor REAL DEFAULT 1.5;",
]

# Phase 10: Parallel execution tables + task_graphs parallel columns (8 → 9)
MIGRATION_8_TO_9 = [
    """CREATE TABLE IF NOT EXISTS execution_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);""",
    "CREATE INDEX IF NOT EXISTS idx_exec_slots_task ON execution_slots(task_id);",
    "CREATE INDEX IF NOT EXISTS idx_exec_slots_agent ON execution_slots(agent_id);",
    "CREATE INDEX IF NOT EXISTS idx_exec_slots_status ON execution_slots(status);",
    """CREATE TABLE IF NOT EXISTS resource_locks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_path TEXT NOT NULL,
    locked_by TEXT NOT NULL,
    waiting_tasks TEXT NOT NULL DEFAULT '[]',
    lock_type TEXT NOT NULL DEFAULT 'write',
    acquired_at TEXT NOT NULL,
    FOREIGN KEY (locked_by) REFERENCES tasks(id) ON DELETE CASCADE
);""",
    "CREATE INDEX IF NOT EXISTS idx_resource_locks_path ON resource_locks(resource_path);",
    "CREATE INDEX IF NOT EXISTS idx_resource_locks_task ON resource_locks(locked_by);",
    "ALTER TABLE task_graphs ADD COLUMN parallel_mode TEXT DEFAULT 'auto';",
    "ALTER TABLE task_graphs ADD COLUMN max_parallel_slots INTEGER DEFAULT 10;",
    "ALTER TABLE task_graphs ADD COLUMN resource_conflict_policy TEXT DEFAULT 'warn';",
    # Phase 10.2: RBAC tables
    """CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    permissions_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);""",
    """CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id TEXT NOT NULL UNIQUE,
    token_hash TEXT NOT NULL UNIQUE,
    principal_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'agent',
    scopes TEXT NOT NULL DEFAULT '[]',
    tenant_id TEXT DEFAULT 'default',
    expires_at TEXT,
    is_revoked INTEGER DEFAULT 0,
    revoked_at TEXT,
    created_at TEXT NOT NULL
);""",
    """CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_role TEXT,
    action TEXT NOT NULL,
    resource TEXT,
    details_json TEXT,
    timestamp TEXT NOT NULL,
    tenant_id TEXT DEFAULT 'default'
);""",
    "CREATE INDEX IF NOT EXISTS idx_tokens_principal ON tokens(principal_id);",
    "CREATE INDEX IF NOT EXISTS idx_tokens_hash ON tokens(token_hash);",
    "CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(tenant_id, actor_id);",
    "CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(tenant_id, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event_type);",
]

# Phase 11.1b: Agent config column (schema version 9 → 10)
MIGRATION_9_TO_10 = [
    """ALTER TABLE agents ADD COLUMN allowed_discussion_roles TEXT DEFAULT '["participant"]';""",
]

# Phase 12.5a: Session + artifact tables (schema version 10 → 11)
MIGRATION_10_TO_11 = [
    """CREATE TABLE IF NOT EXISTS session_records (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT 'default',
    session_type TEXT NOT NULL DEFAULT 'task_execution',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    input_messages TEXT DEFAULT '[]',
    output_messages TEXT DEFAULT '[]',
    tool_calls TEXT DEFAULT '[]',
    errors TEXT DEFAULT '[]',
    outcome TEXT DEFAULT 'success',
    metadata TEXT DEFAULT '{}',
    notes TEXT DEFAULT '[]',
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);""",
    "CREATE INDEX IF NOT EXISTS idx_sessions_agent ON session_records(agent_id);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_project ON session_records(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_outcome ON session_records(outcome);",
    """CREATE TABLE IF NOT EXISTS session_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES session_records(id) ON DELETE CASCADE
);""",
    "CREATE INDEX IF NOT EXISTS idx_session_notes_session ON session_notes(session_id);",
    """CREATE TABLE IF NOT EXISTS project_artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value BLOB,
    content_type TEXT DEFAULT 'application/octet-stream',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, key)
);""",
    "CREATE INDEX IF NOT EXISTS idx_artifacts_project ON project_artifacts(project_id);",
]

# Phase 13: Pipeline runs table (schema version 11 -> 12)
MIGRATION_11_TO_12 = [
    """CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    idea TEXT NOT NULL,
    motion_id TEXT,
    graph_id TEXT,
    phase TEXT NOT NULL DEFAULT 'discussing',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    tasks_total INTEGER NOT NULL DEFAULT 0,
    tasks_completed INTEGER NOT NULL DEFAULT 0,
    tasks_failed INTEGER NOT NULL DEFAULT 0,
    review_outcome TEXT,
    release_version TEXT,
    error TEXT,
    failed_phase TEXT
);""",
    "CREATE INDEX IF NOT EXISTS idx_pipeline_runs_project ON pipeline_runs(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_pipeline_runs_phase ON pipeline_runs(phase);",
]

# Phase 13b: Add failed_phase column to existing pipeline_runs (12 → 13)
MIGRATION_12_TO_13_PIPELINES = [
    "ALTER TABLE pipeline_runs ADD COLUMN failed_phase TEXT;",
]

# Phase 13: Notifications table (schema version 12 → 13)
MIGRATION_12_TO_13 = [
    """CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    project_id TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'medium',
    created_at TEXT NOT NULL,
    read INTEGER NOT NULL DEFAULT 0
);""",
    "CREATE INDEX IF NOT EXISTS idx_notifications_project ON notifications(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type);",
]

# Phase 14: Workspace file_nodes + file_locks tables (schema 14 → 15)
MIGRATION_14_TO_15 = [
    """CREATE TABLE IF NOT EXISTS file_nodes (
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
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(project_id, path)
);""",
    "CREATE INDEX IF NOT EXISTS idx_file_nodes_project "
    "ON file_nodes(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_file_nodes_parent "
    "ON file_nodes(project_id, parent_path);",
    "CREATE INDEX IF NOT EXISTS idx_file_nodes_type "
    "ON file_nodes(project_id, file_type);",
    """CREATE TABLE IF NOT EXISTS file_locks (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    path TEXT NOT NULL,
    lock_type TEXT NOT NULL DEFAULT 'write',
    held_by TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (file_id) REFERENCES file_nodes(id) ON DELETE CASCADE
);""",
    "CREATE INDEX IF NOT EXISTS idx_file_locks_path "
    "ON file_locks(project_id, path);",
    "CREATE INDEX IF NOT EXISTS idx_file_locks_holder "
    "ON file_locks(held_by);",
]

# Phase 14.5b: Add workspace_paths column to tasks (schema 15 → 16)
MIGRATION_15_TO_16 = [
    "ALTER TABLE tasks ADD COLUMN workspace_paths TEXT DEFAULT '[]';",
]

# Phase 14+ Part D: Webhook tables (schema 16 → 17)
MIGRATION_16_TO_17 = [
    """CREATE TABLE IF NOT EXISTS webhooks (
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
);""",
    "CREATE INDEX IF NOT EXISTS idx_webhooks_project ON webhooks(project_id);",
    """CREATE TABLE IF NOT EXISTS webhook_trigger_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_id TEXT NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
    event TEXT NOT NULL,
    success INTEGER NOT NULL,
    pipeline_id TEXT,
    error TEXT,
    source_ip TEXT,
    triggered_at TEXT NOT NULL
);""",
    "CREATE INDEX IF NOT EXISTS idx_webhook_history_webhook ON webhook_trigger_history(webhook_id);",
]

# Phase 14+.E.3: Add task_result column for structured task results (17 → 18)
# NOTE: The migration runner checks for column existence before executing.
MIGRATION_17_TO_18 = [
    "ALTER TABLE tasks ADD COLUMN task_result TEXT;",
]

# Phase 15.C: Add registration_token column for agent self-registration (18 → 19)
MIGRATION_18_TO_19 = [
    "ALTER TABLE agents ADD COLUMN registration_token TEXT DEFAULT '';",
]

# Phase 16.4: MCP sessions table (schema 19 → 20)
MIGRATION_19_TO_20 = [
    """CREATE TABLE IF NOT EXISTS mcp_sessions (
    mcp_session_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    connected_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    transport_type TEXT DEFAULT 'streamable-http'
);""",
    "CREATE INDEX IF NOT EXISTS idx_mcp_sessions_agent ON mcp_sessions(agent_id);",
]

# Phase 17: Add contact_url column for callback notifications (20 → 21)
MIGRATION_20_TO_21 = [
    "ALTER TABLE agents ADD COLUMN contact_url TEXT DEFAULT NULL;",
]

# Phase 18: Make motion_id nullable in task_graphs and tasks (21 → 22)
# SQLite doesn't support ALTER COLUMN, so we recreate the tables.
MIGRATION_21_TO_22 = [
    # Recreate task_graphs with nullable motion_id
    "ALTER TABLE task_graphs RENAME TO task_graphs_old;",
    """CREATE TABLE task_graphs (
    id TEXT PRIMARY KEY,
    motion_id TEXT UNIQUE,
    created_at TEXT NOT NULL,
    parallel_mode TEXT DEFAULT 'auto',
    max_parallel_slots INTEGER DEFAULT 10,
    resource_conflict_policy TEXT DEFAULT 'warn',
    FOREIGN KEY (motion_id) REFERENCES motions(id) ON DELETE CASCADE
);""",
    "INSERT INTO task_graphs SELECT * FROM task_graphs_old;",
    "DROP TABLE task_graphs_old;",
    # Recreate tasks with nullable motion_id
    "ALTER TABLE tasks RENAME TO tasks_old;",
    """CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    motion_id TEXT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    assigned_to TEXT,
    required_capabilities TEXT,
    depends_on TEXT,
    artifact_paths TEXT,
    workspace_paths TEXT DEFAULT '[]',
    error_message TEXT,
    task_result TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (graph_id) REFERENCES task_graphs(id) ON DELETE CASCADE,
    FOREIGN KEY (motion_id) REFERENCES motions(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_to) REFERENCES agents(agent_id)
);""",
    "INSERT INTO tasks SELECT * FROM tasks_old;",
    "DROP TABLE tasks_old;",
    # Recreate indexes
    "CREATE INDEX IF NOT EXISTS idx_tasks_graph ON tasks(graph_id);",
    "CREATE INDEX IF NOT EXISTS idx_tasks_motion ON tasks(motion_id);",
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);",
    "CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to);",
]

# Phase 19: Pending notifications queue + telegram_chat_id (22 → 23)
MIGRATION_22_TO_23 = [
    """CREATE TABLE IF NOT EXISTS pending_notifications (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    notification_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    acked_at TEXT,
    expires_at TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);""",
    "CREATE INDEX IF NOT EXISTS idx_pend_notif_agent ON pending_notifications(agent_id, status);",
    "CREATE INDEX IF NOT EXISTS idx_pend_notif_status ON pending_notifications(status);",
    "ALTER TABLE agents ADD COLUMN telegram_chat_id TEXT DEFAULT NULL;",
]

# Phase 19+: Matrix wakeup — matrix_user_id (23 → 24)
MIGRATION_23_TO_24 = [
    "ALTER TABLE agents ADD COLUMN matrix_user_id TEXT DEFAULT NULL;",
]

# Default RBAC roles to seed on fresh DB
DEFAULT_ROLES = {
    "admin": [
        "agent:approve", "agent:config", "agent:delete",
        "discussion:moderate", "task:view", "task:assign",
        "tenant:manage", "system:metrics", "system:config",
    ],
    "agent": [
        "agent:register", "discussion:create", "discussion:view",
        "task:view", "task:execute", "system:metrics",
    ],
    "observer": [
        "discussion:view", "task:view", "system:metrics",
    ],
}
