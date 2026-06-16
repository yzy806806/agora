# DESIGN-phase14plus.md — Phase 14+: Horizontal Scaling + Postgres

> Version: v0.15.0-draft | Date: 2026-06-16 | Author: planner

## Background

Agora v0.14.0 is a single-instance system: one Coordinator process backed by SQLite,
one WebSocket connection pool in memory, and Docker Compose for deployment. This
works for ~50 agents on a single host but cannot scale beyond that.

Phase 14 (Shared Workspace) laid the groundwork for distributed agents by
providing network-accessible file storage. Phase 14+ completes the story by
making the Coordinator itself horizontally scalable — multiple Coordinator
instances behind a load balancer, with shared Postgres, a message bus for WS
broadcast fan-out, and Kubernetes-native deployment.

## Direction Evaluation

| Direction | Importance | Urgency | Feasibility | Complexity | Recommendation |
|---|---|---|---|---|---|
| SQLite → Postgres migration | ★★★★★ | ★★★★★ | ★★★★ | High | **Part A** |
| Message queue (WS decouple) | ★★★★★ | ★★★★★ | ★★★★ | Medium | **Part B** |
| Kubernetes Helm Chart | ★★★★ | ★★★★ | ★★★★ | Medium | **Part C** |
| Webhook triggers | ★★★★ | ★★★ | ★★★★★ | Low-Medium | **Part D** |
| Agent Protocol v2 | ★★★★★ | ★★★★ | ★★★★★ | Low | **Part E** |

### Why Now (After Workspace)

1. **Postgres is the next bottleneck** — Workspace content is stored as files (not DB
   BLOBs), but metadata (file_nodes, file_locks) lives in SQLite. At scale, SQLite's
   single-writer lock becomes the bottleneck for concurrent workspace operations.
2. **WS broadcast doesn't scale** — Currently `ConnectionHub.broadcast()` iterates
   over in-memory connections. With multi-instance Coordinator, instance A can't
   reach agents connected to instance B.
3. **User demand for K8s** — Docker Compose is fine for single-host, but serious
   deployments need Kubernetes.
4. **Webhook unlocks CI/CD** — External triggers make Agora a first-class
   participant in DevOps workflows.

---

## Part A: SQLite → Postgres Migration

### A.1 Design Principle: Abstract Storage Backend

The current `Storage` class hardcodes `aiosqlite`. We introduce a **StorageBackend
ABC** with two implementations:

```
StorageBackend (ABC)
├── SqliteBackend    (current, aiosqlite)
└── PostgresBackend  (new, asyncpg)
```

The `Storage` class becomes a facade that delegates to the active backend. This
is the same pattern used for Workspace storage backends (Phase 14's
`StorageBackend` ABC → `LocalFileBackend` / `S3Backend`).

### A.2 Configuration

```yaml
# config.yaml — Phase 14+
database:
  backend: "sqlite"             # "sqlite" or "postgres"
  # SQLite config
  db_path: "/data/agora.db"     # path to SQLite file
  # Postgres config
  database_url: "postgresql://user:pass@host:5432/agora"
  # Postgres: connection pool
  pool_min_size: 2
  pool_max_size: 20
  pool_acquire_timeout: 30
```

Environment variable override: `AGORA_DATABASE_URL`. When set, it overrides
`database.backend` to `"postgres"` and uses the URL directly — this is the
12-factor way for K8s deployments.

### A.3 Schema Mapping

SQLite → Postgres type mapping:

| SQLite type | Postgres type | Notes |
|---|---|---|
| INTEGER PRIMARY KEY AUTOINCREMENT | SERIAL / BIGSERIAL | Seq-based |
| TEXT PRIMARY KEY | UUID / TEXT PRIMARY KEY | Keep TEXT for IDs that are not numeric |
| TEXT (ISO timestamps) | TIMESTAMPTZ | Use proper datetime types |
| INTEGER (boolean) | BOOLEAN | Native boolean type |
| TEXT (JSON arrays) | JSONB | Queryable JSON, replaces `TEXT` for `capabilities`, `active_tasks`, etc. |
| TEXT | TEXT | Same |
| BLOB | BYTEA | For `project_artifacts.value` |
| REAL | DOUBLE PRECISION | Floating point |

Key decisions:
- **No synthetic UUID** — Existing IDs (agent_id, motion_id, task_id) are already
  strings. They remain TEXT/VARCHAR. We don't force UUID format.
- **JSONB for structured fields** — Where SQLite stored JSON strings (`TEXT`),
  Postgres uses `JSONB` with GIN indexes for queryability. This enables
  efficient filtering like `SELECT * FROM agents WHERE capabilities @> '["code-review"]'`.
- **TIMESTAMPTZ** — All timestamp columns become `TIMESTAMPTZ`. Code already uses
  ISO 8601 strings; `asyncpg` auto-converts between Python `datetime` and
  `TIMESTAMPTZ`.

### A.4 Schema Migration

**Full DDL for Postgres:**

```sql
-- Migration path: SQLite dump → transform → Postgres load

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
    motion_id TEXT NOT NULL UNIQUE REFERENCES motions(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL,
    parallel_mode TEXT DEFAULT 'auto',
    max_parallel_slots INTEGER DEFAULT 10,
    resource_conflict_policy TEXT DEFAULT 'warn'
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL REFERENCES task_graphs(id) ON DELETE CASCADE,
    motion_id TEXT NOT NULL REFERENCES motions(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    assigned_to TEXT REFERENCES agents(agent_id),
    required_capabilities JSONB,
    depends_on JSONB,
    artifact_paths JSONB,
    workspace_paths JSONB DEFAULT '[]',
    error_message TEXT,
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

-- Indexes (Phase 14+ additions: JSONB GIN indexes for queryable fields)
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
-- New Phase 14+ JSONB GIN indexes
CREATE INDEX IF NOT EXISTS idx_agents_capabilities_gin ON agents USING GIN (capabilities);
CREATE INDEX IF NOT EXISTS idx_tasks_required_caps_gin ON tasks USING GIN (required_capabilities);
CREATE INDEX IF NOT EXISTS idx_tasks_depends_on_gin ON tasks USING GIN (depends_on);
```

### A.5 Storage Backend ABC

```python
# agora/coordinator/storage/backend.py
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional


class StorageBackend(ABC):
    """Abstract backend for database operations."""

    @asynccontextmanager
    async def connection(self) -> AsyncIterator:
        """Yield a raw connection-like object."""
        ...

    @abstractmethod
    async def init_db(self) -> None:
        """Initialize schema and run migrations."""
        ...

    @abstractmethod
    async def execute(self, sql: str, *params) -> int:
        """Execute a non-returning SQL statement. Returns rowcount."""
        ...

    @abstractmethod
    async def fetch_one(self, sql: str, *params) -> Optional[dict]:
        """Fetch a single row as dict, or None."""
        ...

    @abstractmethod
    async def fetch_all(self, sql: str, *params) -> list[dict]:
        """Fetch all matching rows as list of dicts."""
        ...

    @abstractmethod
    async def fetch_val(self, sql: str, *params):
        """Fetch a single scalar value."""
        ...

    @abstractmethod
    async def executemany(self, sql: str, params_list: list) -> int:
        """Execute with many parameter sets. Returns rowcount."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close backend connections."""
        ...
```

**SqliteBackend** wraps `aiosqlite` (current code, unchanged logic).
**PostgresBackend** wraps `asyncpg` with a connection pool.

The key abstraction challenge: `aiosqlite` uses `?` placeholders; `asyncpg` uses
`$1, $2, ...`. The facade pattern means the `Storage` class emits SQL with `?`
and the backend normalizes. However, a cleaner approach is to have the
**Storage class emit dialect-appropriate SQL** by checking `self.backend.dialect`.
This matches how SQLAlchemy Core works, but much lighter.

### A.6 Migration Tool

Provide a CLI command: `agora migrate --from sqlite:///data/agora.db --to postgres://...`

The migration tool:
1. Reads all rows from SQLite
2. Transforms: `INTEGER` booleans → Python bool, `TEXT` timestamps → Python datetime
3. Writes to Postgres using `asyncpg.copy_to_table()` for bulk insert
4. Resets sequences for BIGSERIAL columns
5. Verifies row counts match

### A.7 Code Changes Summary

| Area | Change |
|---|---|
| `storage/storage.py` | `Storage.__init__` takes config, creates backend |
| `storage/backend.py` | New: StorageBackend ABC |
| `storage/backend_sqlite.py` | New: SqliteBackend |
| `storage/backend_postgres.py` | New: PostgresBackend |
| `storage/schema.py` | Add Postgres DDL, migrate to JSONB-aware queries |
| `storage/*.py` (all sub-modules) | Parameterized queries work with both `?` and `$N` (via backend dialect) |
| `config.py` / `config.yaml` | Add `database` section |
| `cli.py` | Add `agora migrate` subcommand |
| `Dockerfile` | Add `asyncpg` dependency |
| `requirements / pyproject.toml` | Add `asyncpg>=0.29` |

### A.8 Backward Compatibility

- **Default stays SQLite** — `database.backend: "sqlite"` is the default. No
  existing deployment breaks.
- **SQLite still works** — SqliteBackend is maintained alongside; single-instance
  deployments stay simple.
- **Config migration** — Old `AGORA_DB_PATH` env var mapped to `database.db_path`
  and `database.backend: "sqlite"`.

---

## Part B: Message Queue (WS Broadcast Decouple)

### B.1 Problem

Currently, `ConnectionHub.broadcast()` iterates in-process WebSocket connections.
With N Coordinator instances:
- Agent A connects to instance 1
- Agent B connects to instance 2
- Instance 1 cannot send messages to Agent B — they're in different process
  memory spaces.

### B.2 Solution: Redis Pub/Sub (Recommended)

**Why Redis over NATS:**
- Redis is already well-known, widely deployed, and has mature Python async
  client (`redis-py` with `redis.asyncio`).
- Redis Pub/Sub is dead-simple: publish to channel, subscribers receive.
- NATS is more powerful but overkill here — we only need fan-out, not
  persistence or complex routing.
- Redis can also serve as a lock manager for distributed file locks (Phase 14
  workspace locks) and as a rate-limit counter store.

**Architecture:**

```
┌───────────────────────────────────────────────┐
│                  Redis Pub/Sub                 │
│  Channel: agora:{tenant}:ws:broadcast          │
└──────┬──────────────────────────┬─────────────┘
       │ subscribe                │ subscribe
┌──────▼──────┐            ┌──────▼──────┐
│ Coordinator │            │ Coordinator │
│ Instance 1  │            │ Instance 2  │
│  WS conns:  │            │  WS conns:  │
│  agent-A    │            │  agent-B    │
│  agent-C    │            │  agent-D    │
└─────────────┘            └─────────────┘
```

**Flow:**
1. Coordinator publishes message to `agora:{tenant}:ws:broadcast` channel
2. All Coordinator instances subscribe to the channel
3. Each instance receives the message and sends to its local WS connections
4. The publishing instance also sends locally (no exclusion needed)

**Message format on Redis:**

```json
{
  "type": "ws_broadcast",
  "tenant": "default",
  "payload": {"type": "new_message", "motion_id": "...", ...},
  "exclude": [],          // agent_ids to exclude (e.g., the sender)
  "source_instance": "inst-3"
}
```

### B.3 Implementation: BroadcastBus

```python
# agora/coordinator/broadcast_bus.py

from abc import ABC, abstractmethod
from typing import Any


class BroadcastBus(ABC):
    """Decouples WS broadcast across Coordinator instances."""

    @abstractmethod
    async def publish(self, tenant: str, message: dict[str, Any],
                      exclude: list[str] | None = None) -> None:
        """Publish a message to all instances for the given tenant."""
        ...

    @abstractmethod
    async def subscribe(self, tenant: str,
                        handler) -> None:
        """Register a handler for incoming broadcasts."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Shutdown the bus."""
```

**Implementations:**

| Class | Description |
|---|---|
| `LocalBus` | Default — in-process broadcast (current behavior). No external deps. |
| `RedisBus` | Redis Pub/Sub-backed broadcast. Requires `redis` Python package. |

**LocalBus** is a no-op on publish (the in-process broadcast still happens via
`ConnectionHub.broadcast()`). It exists so code always calls `bus.publish()`
without an `if bus is not None` branch.

**RedisBus**:
- On startup: opens a single Redis connection for subscribing, and a pool
  for publishing.
- `publish()` → `await redis.publish(f"agora:{tenant}:ws", json.dumps(msg))`
- `subscribe()` → starts an asyncio task that listens on `agora:{tenant}:ws`
  pattern and calls the handler for each message.

### B.4 ConnectionHub Changes

```python
class ConnectionHub:
    def __init__(self, bus: BroadcastBus | None = None):
        self._bus = bus  # Optional bus for cross-instance broadcast

    async def broadcast(self, message, exclude=None):
        # 1. Local broadcast (in-process WS connections)
        n_local = await self._broadcast_local(message, exclude)
        # 2. Cross-instance broadcast via bus (if configured)
        if self._bus is not None:
            await self._bus.publish(
                self.tenant, message, exclude=exclude
            )
        return n_local  # Return local count (can't count remote)
```

On receiving a Redis message, the bus subscriber calls `_broadcast_local()`
to forward to locally connected agents.

### B.5 Topology Decision: Sticky Sessions Required

WS connections are stateful — an agent's WS is pinned to one instance. This
means:

- **Load balancer MUST use sticky sessions** (cookie-based or IP-hash) for WS
  upgrade requests (`GET /ws/{agent_id}`).
- REST API calls can be routed to any instance (they all share Postgres).
- Dashboard WS follows the same sticky session rule.

For Kubernetes, sticky sessions are configured via Ingress annotations or
Service `sessionAffinity: ClientIP`.

### B.6 Startup Flow

```python
# main.py lifespan
async def lifespan(app):
    # 1. Create storage backend (SqliteBackend or PostgresBackend)
    backend = create_storage_backend(settings)
    storage = Storage(backend)
    await storage.init_db()

    # 2. Create broadcast bus
    if settings.redis_url:
        bus = RedisBus(settings.redis_url)
        await bus.connect()
    else:
        bus = LocalBus()

    # 3. Create connection hub with bus
    hub = ConnectionHub(bus=bus)
    hub.set_deps(storage, sm)

    # 4. Subscribe to broadcasts
    await bus.subscribe("default", hub._on_remote_broadcast)

    app.state.storage = storage
    app.state.bus = bus
    yield
    await bus.close()
    await backend.close()
```

### B.7 Redis Dependencies

- `redis>=5.0` with `redis.asyncio` (async support since redis-py 4.2)
- Redis 6.0+ (Pub/Sub works on all versions; we don't need Streams or other
  newer features for this use case)
- Optional: Redis Cluster / Sentinel for HA (not in scope for Phase 14+)

---

## Part C: Kubernetes Helm Chart

### C.1 What We Replace

Current: `docker-compose.prod.yaml` — single-host, single coordinator, volume
mounts for data.

Target: Helm chart that deploys:
1. N Coordinator instances (Deployment with `replicas: N`)
2. Postgres (optional: can use external DB)
3. Redis (optional: only when `redis_url` is set)
4. Hermes Bridge (separate Deployment)
5. Ingress for WS + REST
6. Persistence for Workspace files (PVC → S3 if needed)

### C.2 Chart Structure

```
deploy/helm/agora/
├── Chart.yaml
├── values.yaml
├── values-prod.yaml          # production overrides
├── templates/
│   ├── _helpers.tpl
│   ├── coordinator-deployment.yaml
│   ├── coordinator-service.yaml
│   ├── coordinator-hpa.yaml  # HorizontalPodAutoscaler
│   ├── hermes-bridge-deployment.yaml
│   ├── hermes-bridge-service.yaml
│   ├── redis-deployment.yaml
│   ├── redis-service.yaml
│   ├── postgres-statefulset.yaml
│   ├── postgres-service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secrets.yaml
│   ├── pvc.yaml              # Workspace files
│   └── servicemonitor.yaml   # Prometheus Operator
└── crds/                     # Custom Resource Definitions (future)
```

### C.3 Key Values

```yaml
# values.yaml
replicaCount: 3
image:
  coordinator: ghcr.io/yzy806806/agora-coordinator:v0.15.0
  hermesBridge: ghcr.io/yzy806806/agora-hermes-bridge:v0.15.0

coordinator:
  resources:
    requests: {cpu: 250m, memory: 256Mi}
    limits: {cpu: "1", memory: 512Mi}
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 10
    targetCPUUtilizationPercentage: 70
  # Pod anti-affinity: spread across nodes
  affinity:
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          podAffinityTerm:
            labelSelector: {matchLabels: {app: agora-coordinator}}
            topologyKey: kubernetes.io/hostname

database:
  # Option A: embedded Postgres (for small deployments)
  embedded:
    enabled: true
    storage: 10Gi
  # Option B: external Postgres (for production)
  externalUrl: ""  # e.g. "postgresql://user:pass@host:5432/agora"

redis:
  # Option A: embedded Redis (for small deployments)
  embedded:
    enabled: true
  # Option B: external Redis
  externalUrl: ""  # e.g. "redis://host:6379/0"

workspace:
  storage:
    # "local" (PVC) or "s3"
    backend: "local"
    pvc:
      size: 20Gi
    s3:
      bucket: ""
      endpoint: ""
      accessKey: ""
      secretKey: ""

ingress:
  enabled: true
  className: nginx
  host: agora.example.com
  tls:
    enabled: true
    secretName: agora-tls
  annotations:
    # WebSocket support
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
    # Sticky sessions for WS (required for multi-instance)
    nginx.ingress.kubernetes.io/affinity: "cookie"
    nginx.ingress.kubernetes.io/session-cookie-name: "AGORA_WS_ROUTE"
    nginx.ingress.kubernetes.io/session-cookie-path: "/"
    nginx.ingress.kubernetes.io/session-cookie-max-age: "86400"

jwtSecret:
  # Set via `--set jwtSecret.value=...` or external secret
  existingSecret: ""
  value: ""  # generate: openssl rand -hex 32

monitoring:
  serviceMonitor:
    enabled: true
    interval: 30s
```

### C.4 Deployment Considerations

| Concern | Solution |
|---|---|
| **WebSocket sticky sessions** | NGINX Ingress `affinity: cookie` annotation |
| **Database migrations on startup** | Init container runs `agora migrate --check` |
| **Workspace files** | PVC for local backend, S3 for distributed |
| **Secrets** | JWT secret via Kubernetes Secret, DB URL from secret |
| **Health check** | `/api/v1/health` endpoint (already exists, Phase 13.7b) |
| **Graceful shutdown** | `terminationGracePeriodSeconds: 30`, drain WS connections |
| **Rolling updates** | `strategy: RollingUpdate`, `maxSurge: 1, maxUnavailable: 0` |

### C.5 What We Don't Include (Yet)

- **Postgres HA** (Patroni, pgBouncer) — defer to Phase 15+. Users bring their
  own Postgres or use the embedded single-instance one.
- **Redis Sentinel/Cluster** — defer. Embedded Redis is single-instance;
  production users bring their own Redis.
- **S3 MinIO operator** — Users bring S3-compatible storage.
- **Multi-region / geo-replication** — Not in scope.

---

## Part D: Webhook Triggers

### D.1 Motivation

Currently, Pipeline starts are gated by discussion → motion → vote → pipeline.
Webhooks allow triggering a Pipeline from external events:
- GitHub push → start dev pipeline
- CI failure → start diagnostic discussion
- Monitoring alert → start incident response pipeline
- Scheduled cron → periodic maintenance pipeline
- Custom webhook from any system

### D.2 Webhook Model

```python
# agora/coordinator/webhook_models.py
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class WebhookConfig(BaseModel):
    """Registered webhook endpoint configuration."""
    id: str                          # Unique webhook ID
    project_id: str
    name: str                        # Human-readable
    description: str = ""
    secret: str                      # HMAC secret for payload verification
    pipeline_template: str           # JSON template for pipeline creation
    events: list[str] = ["push"]     # Event types to accept
    enabled: bool = True
    created_at: datetime
    last_triggered_at: Optional[datetime] = None
    trigger_count: int = 0
    failure_count: int = 0


class WebhookEvent(BaseModel):
    """Incoming webhook payload (after verification)."""
    webhook_id: str
    event: str                       # e.g. "push", "pull_request", "custom"
    payload: dict                    # The actual webhook body
    headers: dict                    # Request headers (for signature)
    signature: str                   # HMAC signature
    source_ip: str
```

### D.3 API Endpoints

```
POST   /api/v1/webhooks              # Register a webhook config
GET    /api/v1/webhooks/{id}         # Get webhook config
PUT    /api/v1/webhooks/{id}         # Update webhook config
DELETE /api/v1/webhooks/{id}         # Delete webhook config
POST   /api/v1/webhooks/{id}/trigger # The actual webhook trigger endpoint (external callers hit this)
GET    /api/v1/webhooks/{id}/history # Trigger history
```

### D.4 Trigger Flow

```
External System (GitHub, CI, etc.)
    │
    │ POST /api/v1/webhooks/{id}/trigger
    │ Headers: X-Agora-Signature: sha256=...
    │ Body: { "event": "push", ... }
    ▼
┌─────────────────────┐
│ Signature Verification │ → HMAC-SHA256(secret, body) == signature?
└────────┬────────────┘
         │ ✓
         ▼
┌─────────────────────┐
│ Template Rendering   │ → Merge event payload into pipeline_template
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ Pipeline Creation    │ → Same flow as Phase 13 PipelineOrchestrator.start()
│                      │   idea = template.idea
│                      │   project_id = webhook.project_id
│                      │   metadata.webhook_id = webhook.id
└────────┬────────────┘
         │
         ▼
    202 Accepted { pipeline_id, status }
```

### D.5 Pipeline Template

```json
{
  "idea": "{{ event.payload.head_commit.message | default('Webhook-triggered pipeline') }}",
  "project_id": "{{ webhook.project_id }}",
  "context": "Triggered by webhook \"{{ webhook.name }}\" ({{ event.event }})",
  "auto_approve": false,
  "max_parallel_slots": 8,
  "metadata": {
    "webhook_id": "{{ webhook.id }}",
    "event": "{{ event.event }}",
    "source": "{{ event.source_ip }}"
  }
}
```

Uses Jinja2 (already in Agora dependency tree via FastAPI) for template rendering.
Safe: only the webhook owner can set the template; external callers can't inject
arbitrary template content.

### D.6 Security

| Measure | How |
|---|---|
| **Signature verification** | HMAC-SHA256 over request body. Header: `X-Agora-Signature: sha256=<hex>`. Secret is per-webhook, stored hashed. |
| **IP allowlisting** | Optional per-webhook `allowed_ips: ["1.2.3.0/24"]` |
| **Rate limiting** | Per-webhook max triggers/min (default 60/h, configurable). Prevent abuse. |
| **RBAC** | `agora.webhook.manage` permission for CRUD endpoints. `agora.webhook.trigger` for the trigger endpoint (available to agents). |
| **Secret rotation** | `PUT /webhooks/{id}` with new `secret` — old signatures rejected post-rotation. |

### D.7 Webhook Signature (GitHub-compatible)

Following GitHub's webhook signature pattern:
```
X-Agora-Signature-256: sha256=<hex-encoded HMAC>
```

Verification:
```python
import hmac, hashlib

def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    expected = hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

### D.8 Database Changes

```sql
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

CREATE INDEX IF NOT EXISTS idx_webhooks_project ON webhooks(project_id);
CREATE INDEX IF NOT EXISTS idx_webhook_history_webhook ON webhook_trigger_history(webhook_id);
```

---

## Part E: Agent Protocol v2

### E.1 What's Wrong with v1

The current agent protocol (Phase 9.3) works but has accumulated cruft and
missed opportunities:

1. **Flat capability strings** — `capabilities: ["code-review", "python"]` is
   too simplistic. No proficiency levels, no areas of expertise.
2. **No protocol version negotiation** — Agents can't declare which protocol
   version they support. New features break old agents.
3. **HEARTBEAT includes `active_tasks`** but not `workspace_operations`, which
   matters for understanding agent load.
4. **No structured error reporting** — Task failures are just `error_message:
   string`. No error codes, retry hints, or structured diagnostics.
5. **No agent metadata** — Agents can't describe themselves beyond `name` and
   `model`. No home page, docs URL, or version string.
6. **Token-based auth is bare-bones** — No token scopes per-agent, no
   token refresh, no rotation.
7. **No protocol discovery** — Agents can't ask "what can I do here?" before
   registering.

### E.2 Protocol Version Negotiation

```
Agent connects via WS → Coordinator sends WELCOME:
{
  "type": "welcome",
  "protocol_version": "2.0",              // Max version coordinator supports
  "server_version": "0.15.0",
  "session_id": "sess-abc123",
  "capabilities": {                       // What the coordinator can do
    "discussion": true,
    "task_execution": true,
    "workspace": true,
    "webhooks": true
  }
}

Agent responds with CAPABILITIES message:
{
  "type": "capabilities",
  "protocol_version": "2.0",              // Agent's preferred version (≤ server)
  "name": "dev-merger-v3",
  "model": "claude-sonnet-4",
  "agent_type": "hermes",
  // New: structured capabilities
  "capabilities": {
    "discussion": {
      "roles": ["participant", "devils_advocate"],
      "voting": true
    },
    "task_execution": {
      "max_concurrent": 2,
      "skills": [
        {"name": "python", "proficiency": "expert"},
        {"name": "code-review", "proficiency": "advanced"},
        {"name": "testing", "proficiency": "intermediate"}
      ]
    },
    "workspace": {
      "supported_operations": ["read", "write", "lock"]
    }
  },
  // New: agent metadata
  "metadata": {
    "version": "3.1.0",
    "homepage": "https://github.com/my-org/dev-merger",
    "description": "Expert code reviewer and merger"
  },
  // New: preferred error reporting format
  "error_format": "structured_v2"
}
```

### E.3 Structured Task Results

**v1:**
```json
{
  "type": "task_complete",
  "task_id": "task-1",
  "success": false,
  "error": "Something went wrong"   // unstructured
}
```

**v2:**
```json
{
  "type": "task_result",
  "task_id": "task-1",
  "status": "failed",               // "success" | "failed" | "partial"
  "output": {
    "changed_files": ["src/foo.py"],
    "tests_run": 12,
    "tests_passed": 10,
    "artifacts": ["/workspace/output/report.pdf"]
  },
  "error": {                        // Structured error (only when failed)
    "code": "TEST_FAILURE",
    "message": "2 tests failed in test_foo.py",
    "details": {
      "failed_tests": ["test_case_1", "test_case_3"],
      "traceback": "AssertionError: ..."
    },
    "retry_hint": "review_test_logic"  // Coordinator can use for retry decisions
  },
  "metrics": {                      // Optional: resource usage
    "wall_time_seconds": 45.2,
    "tokens_used": 15200,
    "peak_memory_mb": 320
  }
}
```

### E.4 Agent Discovery Endpoint

Before registering, agents can hit a REST endpoint to understand what's
available:

```
GET /api/v1/discovery
→ {
  "protocol_versions": ["1.0", "2.0"],
  "server_version": "0.15.0",
  "features": {
    "discussion": {"voting_methods": ["simple_majority", "weighted", "ranked_choice"]},
    "task_execution": {"dependencies": true, "parallel": true},
    "workspace": {"backends": ["local", "s3"]},
    "webhooks": {"enabled": true}
  },
  "rate_limits": {
    "default_tpm": 10000,
    "max_concurrent_tasks": 10
  },
  "auth": {
    "methods": ["token", "hmac"],
    "token_endpoint": "/api/v1/auth/token"
  },
  "api_version": "v1"
}
```

### E.5 Token Scopes (v2 Auth)

Expand the token system to support scoped permissions:

```python
class TokenScope(str, Enum):
    """What an agent token authorizes."""
    REGISTER = "register"           # Can register
    CONNECT = "connect"             # Can open WS
    DISCUSS = "discuss"             # Can participate in discussions
    EXECUTE_TASKS = "execute_tasks" # Can receive and execute tasks
    READ_WORKSPACE = "workspace:read"
    WRITE_WORKSPACE = "workspace:write"
    MANAGE_WORKSPACE = "workspace:manage"  # Create/delete projects
    TRIGGER_WEBHOOKS = "webhooks:trigger"
    MANAGE_WEBHOOKS = "webhooks:manage"
    VIEW_METRICS = "metrics:read"
    ADMIN = "admin"                 # Full access
```

### E.6 Backward Compatibility

- **Protocol version negotiation** means v1 and v2 agents can coexist.
- Coordinator advertises max version; agent picks its preferred version.
- v1 agents get v1 message format (existing behavior).
- v2 agents get structured capabilities, error codes, and discovery.

**Migration path:** No breaking changes. v1 agents continue to work. New
agents adopt v2 features incrementally.

### E.7 Changes Required

| Area | Change |
|---|---|
| `models.py` | Add `AgentCapabilities`, `SkillDeclaration`, `SkillProficiency`, `AgentMetadata`, `TaskResult`, `StructuredError` models |
| `ws_handlers.py` | Handle v2 messages: CAPABILITIES, TASK_RESULT; WELCOME includes protocol version |
| `capability.py` | New `CapabilityMatcher` that scores structured capabilities (proficiency-weighted) |
| `router.py` | Add `GET /api/v1/discovery` endpoint |
| `storage/agents.py` | Store structured capabilities as JSONB |
| `ws_endpoint.py` | Send WELCOME on connect with protocol version |
| `config.py` | Add `AGORA_PROTOCOL_VERSION` (default "2.0") |

---

## Implementation Plan

| Part | Description | Dev Tasks | Est. Days |
|---|---|---|---|
| A | Postgres migration | 8 | 14 |
| B | Message queue (Redis) | 4 | 7 |
| C | K8s Helm Chart | 4 | 7 |
| D | Webhook triggers | 5 | 7 |
| E | Agent Protocol v2 | 6 | 8 |
| **Integration** | End-to-end wiring, docs | 3 | 5 |
| **Total** | | **30** | **48 days** |

### Sub-task Breakdown

**Part A: Postgres (8 tasks)**
- A.1: StorageBackend ABC + SqliteBackend (refactor existing code)
- A.2: PostgresBackend with asyncpg connection pool
- A.3: Schema DDL for Postgres (SQL file + migration)
- A.4: SQL dialect abstraction (replace `?` with appropriate placeholder)
- A.5: Config: database section, AGORA_DATABASE_URL
- A.6: CLI migrate command (sqlite → postgres)
- A.7: Update all storage CRUD modules for backend-agnostic queries
- A.8: Integration tests with real Postgres (testcontainers or Docker fixture)

**Part B: Message Queue (4 tasks)**
- B.1: BroadcastBus ABC + LocalBus
- B.2: RedisBus implementation
- B.3: Wire into ConnectionHub + main.py lifespan
- B.4: Integration tests with Redis fixture

**Part C: Helm Chart (4 tasks)**
- C.1: Chart skeleton + values.yaml (all templates)
- C.2: Coordinator Deployment + HPA + Service
- C.3: Redis + Postgres + Ingress templates
- C.4: Documentation (deploy/helm/agora/README.md)

**Part D: Webhooks (5 tasks)**
- D.1: Webhook models + DB schema
- D.2: Webhook CRUD API (register, get, update, delete)
- D.3: Trigger endpoint + signature verification
- D.4: Template rendering → Pipeline creation
- D.5: Rate limiting + IP allowlisting + tests

**Part E: Agent Protocol v2 (6 tasks)**
- E.1: v2 message models (Capabilities, SkillDeclaration, TaskResult, StructuredError)
- E.2: WELCOME message + protocol negotiation
- E.3: Structured task result handling
- E.4: CapabilityMatcher v2 (proficiency-weighted)
- E.5: Discovery endpoint
- E.6: Token scopes + enhanced auth

### Rollout Order

```
Phase 14+.1: Part A (Postgres) + Part B (Redis) — deployable together
Phase 14+.2: Part C (Helm Chart) — depends on A+B
Phase 14+.3: Part D (Webhooks) + Part E (Protocol v2) — independent of A+B+C
```

---

## Files Summary

| Phase | New Files | Modified Files | DB Changes |
|---|---|---|---|
| A (Postgres) | `storage/backend.py`, `storage/backend_sqlite.py`, `storage/backend_postgres.py`, `cli_migrate.py` | `storage/storage.py`, `storage/schema.py`, `storage/*.py` (all), `config.py`, `Dockerfile`, `pyproject.toml` | Postgres DDL (all tables) |
| B (Redis) | `broadcast_bus.py` | `ws.py`, `main.py`, `config.py` | None |
| C (Helm) | `deploy/helm/agora/*` (12+ files) | None (new tree) | None |
| D (Webhooks) | `webhook_models.py`, `webhook_router.py`, `webhook_verifier.py` | `main.py`, `models.py`, `router.py`, `schema.py` | `webhooks`, `webhook_trigger_history` tables |
| E (Protocol v2) | `capability_v2.py` | `ws_handlers.py`, `ws_endpoint.py`, `models.py`, `capability.py`, `router.py`, `storage/agents.py`, `config.py` | JSONB columns for `capabilities` |

---

## Key Design Decisions

1. **StorageBac*kend ABC, not SQLAlchemy** — We don't need ORM features. A thin
   ABC is sufficient, avoids heavy dependency, and matches the Phase 14
   Workspace pattern.

2. **Redis Pub/Sub, not NATS** — NATS is more powerful but adds operational
   complexity. Redis is already a common dependency for caching/locking and has
   excellent Python support.

3. **Helm, not Kustomize** — Helm is the de facto standard for distributing
   third-party charts. Kustomize is better for in-house overlays; we provide
   values files as the overlay mechanism.

4. **Webhook signature: GitHub-compatible** — Don't invent new auth schemes.
   GitHub webhooks are battle-tested and users already know how to set them up.

5. **Protocol v2 is additive** — v1 agents continue to work. v2 features are
   opt-in via protocol negotiation. No breaking changes.

6. **JSONB for structured fields** — Postgres JSONB enables querying inside
   capabilities, dependencies, and other structured data that was opaque TEXT
   in SQLite.

7. **Workspace content stays as files** — Postgres stores metadata only. File
   content remains in the Workspace storage backend (local/S3). We don't store
   file BLOBs in Postgres — that's a known anti-pattern.
