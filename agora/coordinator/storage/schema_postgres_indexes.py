"""Postgres index definitions for the Agora Coordinator database.

Includes standard B-tree indexes and JSONB GIN indexes for
queryable structured fields (capabilities, required_capabilities, etc.).
"""

PG_INDEXES_SQL = """\
-- Standard B-tree indexes (mirror SQLite indexes)
CREATE INDEX IF NOT EXISTS idx_messages_motion ON messages(motion_id);
CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_id);
CREATE INDEX IF NOT EXISTS idx_messages_round ON messages(motion_id, round_num);
CREATE INDEX IF NOT EXISTS idx_votes_motion ON votes(motion_id);
CREATE INDEX IF NOT EXISTS idx_assessments_motion ON assessments(motion_id);
CREATE INDEX IF NOT EXISTS idx_judgment_agent ON judgment_records(agent_id);
CREATE INDEX IF NOT EXISTS idx_judgment_motion ON judgment_records(motion_id);
CREATE INDEX IF NOT EXISTS idx_bootstrap_triggers_status
    ON bootstrap_triggers(status);
CREATE INDEX IF NOT EXISTS idx_bootstrap_schedules_enabled
    ON bootstrap_schedules(enabled);
CREATE INDEX IF NOT EXISTS idx_bootstrap_approvals_motion
    ON bootstrap_approvals(motion_id);
CREATE INDEX IF NOT EXISTS idx_bootstrap_approvals_status
    ON bootstrap_approvals(approval_status);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_motion ON events(motion_id);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_graph ON tasks(graph_id);
CREATE INDEX IF NOT EXISTS idx_tasks_motion ON tasks(motion_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_rate_limit_agent
    ON rate_limit_usage(agent_id);
CREATE INDEX IF NOT EXISTS idx_exec_slots_task ON execution_slots(task_id);
CREATE INDEX IF NOT EXISTS idx_exec_slots_agent ON execution_slots(agent_id);
CREATE INDEX IF NOT EXISTS idx_exec_slots_status
    ON execution_slots(status);
CREATE INDEX IF NOT EXISTS idx_resource_locks_path
    ON resource_locks(resource_path);
CREATE INDEX IF NOT EXISTS idx_tokens_principal ON tokens(principal_id);
CREATE INDEX IF NOT EXISTS idx_tokens_hash ON tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(tenant_id, actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(tenant_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON session_records(agent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_project
    ON session_records(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_outcome
    ON session_records(outcome);
CREATE INDEX IF NOT EXISTS idx_session_notes_session
    ON session_notes(session_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_project
    ON project_artifacts(project_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_project
    ON pipeline_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_phase
    ON pipeline_runs(phase);
CREATE INDEX IF NOT EXISTS idx_notifications_project
    ON notifications(project_id);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read);
CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type);
CREATE INDEX IF NOT EXISTS idx_file_nodes_project
    ON file_nodes(project_id);
CREATE INDEX IF NOT EXISTS idx_file_nodes_parent
    ON file_nodes(project_id, parent_path);
CREATE INDEX IF NOT EXISTS idx_file_nodes_type
    ON file_nodes(project_id, file_type);
CREATE INDEX IF NOT EXISTS idx_file_locks_path
    ON file_locks(project_id, path);
CREATE INDEX IF NOT EXISTS idx_file_locks_holder
    ON file_locks(held_by);

-- JSONB GIN indexes for queryable structured fields
CREATE INDEX IF NOT EXISTS idx_agents_capabilities_gin
    ON agents USING GIN (capabilities);
CREATE INDEX IF NOT EXISTS idx_tasks_required_caps_gin
    ON tasks USING GIN (required_capabilities);
CREATE INDEX IF NOT EXISTS idx_tasks_depends_on_gin
    ON tasks USING GIN (depends_on);
"""
