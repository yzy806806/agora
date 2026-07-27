# Agora Module Dependencies

> Last updated: v1.7.1

## Overview

Agora is a Hermes Agent plugin. It depends on Hermes core for:
- Plugin registration API (`ctx.register_tool`, `ctx.register_hook`, `ctx.register_cli_command`)
- Kanban task database (`hermes_cli.kanban_db`)
- Profile management (`hermes_cli.profiles`)
- Hermes constants (`hermes_constants.get_hermes_home`)
- Memory store (`tools.memory_tool` / `hermes_cli.memory_tool`)
- Hermes CLI binary (subprocess calls for agent spawning and cron management)
- FastAPI + Pydantic (dashboard API, provided by Hermes dashboard runtime)

No external pip packages beyond what Hermes already provides.

---

## Hermes Core API Dependencies

### Plugin Registration (`ctx`)

Used in `__init__.py:register(ctx)`:

| Method | Purpose |
|--------|---------|
| `ctx.register_tool(name, toolset, schema, handler, ...)` | Register 17 Agora tools (handlers wrapped with `_wrap_handler` / `_wrap_handler_async` to return JSON string) |
| `ctx.register_hook(event_name, callback)` | Register 3 kanban hooks |
| `ctx.register_cli_command(name, help, setup_fn, handler_fn, ...)` | Register `hermes agora` CLI |

> **Important:** Hermes tool registry requires handlers to return `str` (JSON) or multimodal dict, not plain dict. Agora wraps all handlers with `_wrap_handler` (sync) / `_wrap_handler_async` (async) at module level in `tools/__init__.py` to auto-serialize dict returns via `json.dumps(result, ensure_ascii=False)`.

### `hermes_cli.kanban_db`

SQLite module for kanban task management. Used in 6 files:

| Method | Used in | Purpose |
|--------|---------|---------|
| `kanban_db.connect()` | driver, hooks, project_planner, tools, session_manager, dashboard | Get DB connection |
| `kanban_db.create_task(conn, title, body, assignee, ...)` | driver, tools | Create kanban task |
| `kanban_db.get_task(conn, task_id)` | hooks, project_planner, tools | Get task by ID |
| `kanban_db.add_comment(conn, task_id, comment)` | hooks | Add comment to task |
| `kanban_db.block_task(conn, task_id, reason)` | tools | Block a task |
| `kanban_db.list_boards(conn)` | dashboard | List kanban boards |

**DB path**: `~/.hermes/kanban.db` (or `HERMES_KANBAN_DB` env var)

**Schema dependencies**: `tasks` table (id, title, body, assignee, status, tenant, started_at, completed_at, consecutive_failures), `task_runs` table (id, task_id, status, started_at, ended_at, outcome), `task_comments` table.

### `hermes_cli.profiles`

Profile management. Used in `dashboard/plugin_api.py` only:

| Method | Purpose |
|--------|---------|
| `profiles.list_profiles()` | List all Hermes profiles with config summary |
| `profiles.get_profile_dir(name)` | Get profile directory path |
| `profiles.delete_profile(name, yes=True)` | Delete a profile |

### `hermes_constants`

| Function | Used in | Purpose |
|----------|---------|---------|
| `get_hermes_home()` | `utils.py`, `storage/motions.py` | Get `~/.hermes` path |

### `tools.memory_tool` / `hermes_cli.memory_tool`

| Class | Used in | Purpose |
|-------|---------|---------|
| `MemoryStore` | `hooks/__init__.py` | Write motion decisions to leader's MEMORY.md |

Import has fallback: tries `tools.memory_tool` first, then `hermes_cli.memory_tool`.

### Hermes CLI Binary (`hermes`)

Located via `find_hermes_binary()` in `utils.py`. Subprocess calls:

| Command | Used in | Purpose |
|---------|---------|---------|
| `hermes -p <profile> --yolo --accept-hooks --toolsets agora chat -Q -q <prompt>` | agent_spawn.py | Spawn worker/leader for discussion |
| `hermes -p <profile> --yolo --accept-hooks --toolsets agora --resume <sid> chat -Q -q <prompt>` | agent_spawn.py | Resume session |
| `hermes cron create <schedule> --name <name> --no-agent --script <path> --deliver local` | project_planner.py | Create heartbeat cron job |
| `hermes cron remove <job_id>` | project_planner.py | Remove heartbeat cron |
| `hermes cron edit <job_id> --schedule <schedule>` | project_planner.py | Update heartbeat interval |
| `hermes cron pause <job_name>` | project_planner.py | Pause heartbeat |
| `hermes cron resume <job_name>` | project_planner.py | Resume heartbeat |

### FastAPI + Pydantic

Used in `dashboard/plugin_api.py`:

| Import | Purpose |
|--------|---------|
| `APIRouter` | REST API route registration |
| `HTTPException` | Error responses |
| `Query` | Query parameter validation |
| `BaseModel`, `Field` | Request body models |

Graceful fallback: `APIRouter = None` if FastAPI not installed (dashboard not running).

### PyYAML (`yaml`)

Used in `utils.py`, `worker_manager.py`, `dashboard/plugin_api.py` for reading/writing profile `config.yaml`.

---

## Internal Module Dependencies

```
__init__.py (register)
├── tools/__init__.py (register_all_tools)
│   ├── agora.storage.motions (db)
│   ├── project_planner (start/stop/update/status)
│   ├── agora.worker_manager (create/list/remove workers)
│   ├── agora.team_manager (create/list/remove teams)
│   ├── agora.discussion.agent_spawn (spawn_discussion_driver)
│   └── agora.discussion.roles (DISCUSSION_TEMPLATES)
├── hooks/__init__.py (register_hooks)
│   ├── agora.storage.motions (db)
│   ├── project_planner (on_task_completed)
│   ├── agora.worker_manager (get_worker — check is_leader)
│   └── tools.memory_tool / hermes_cli.memory_tool (MemoryStore)
├── cli.py (setup_agora_cli, handle_agora_cli)
│   └── agora.storage.motions (db)
└── dashboard/plugin_api.py (router)
    ├── agora.storage.motions (db)
    ├── project_planner (start/stop/update/status)
    ├── agora.worker_manager (list/create/remove workers)
    ├── agora.team_manager (list/create/remove teams)
    ├── agora.discussion.agent_spawn (spawn_discussion_driver)
    ├── agora.utils (get_registry_dir, safe_name)
    ├── hermes_cli.profiles (list/get/delete)
    └── hermes_cli.kanban_db (connect, list_boards)
```

### `agora/` package

| Module | Depends on | Purpose |
|--------|-----------|---------|
| `agora/utils.py` | hermes_constants, yaml | Shared utilities: `find_hermes_binary`, `get_registry_dir`, `safe_name`, `now_iso`, `get_global_root`, `parse_json_response` |
| `agora/storage/motions.py` | hermes_constants | SQLite storage: motions, messages, votes, discussion_state. WAL + busy_timeout=5000 |
| `agora/discussion/driver.py` | storage/motions, utils, agent_spawn, chair | DiscussionDriver: event-driven discussion loop |
| `agora/discussion/agent_spawn.py` | utils | Spawn real Hermes agent subprocesses. `spawn_agent_speak`, `spawn_chair_speak`, `spawn_discussion_driver` |
| `agora/discussion/chair.py` | (none external) | Chair prompts: opening, evaluation, voting, summary. Speaker prompt builder |
| `agora/discussion/roles.py` | (none external) | Discussion templates (tech_choice, bug_analysis, etc.) |
| `agora/leader_loop.py` | utils, storage/motions, agent_spawn | Heartbeat spawn, stuck motion rescue, stale state cleanup |
| `agora/session_manager.py` | hermes_cli.kanban_db | Session size tracking + rotation. Queries profile-specific state.db |
| `agora/worker_manager.py` | utils, worker_templates | Worker lifecycle: create, list, remove. fcntl-locked session updates |
| `agora/worker_templates.py` | (none external) | 8 role templates (SOUL.md rendering) |
| `agora/team_manager.py` | utils | Team + dispatch routing (role → worker mapping) |

### Top-level modules

| Module | Depends on | Purpose |
|--------|-----------|---------|
| `project_planner.py` | agora.utils, agora.worker_manager, agora.team_manager, agora.leader_loop, hermes_cli.kanban_db | Project lifecycle: start, stop, update, delete. Heartbeat cron management. AGENTS.md generation (atomic write) |
| `cli.py` | agora.storage.motions | `hermes agora` CLI subcommand |
| `hooks/__init__.py` | agora.storage.motions, project_planner, agora.worker_manager, hermes_cli.kanban_db, tools.memory_tool | 3 kanban hooks: completed, claimed, blocked |
| `tools/__init__.py` | agora.storage.motions, project_planner, agora.worker_manager, agora.team_manager, agora.discussion.agent_spawn, agora.discussion.roles, hermes_cli.kanban_db | 17 tool definitions + `/agora` slash command |
| `dashboard/plugin_api.py` | agora.storage.motions, project_planner, agora.worker_manager, agora.team_manager, agora.discussion.agent_spawn, agora.utils, hermes_cli.profiles, hermes_cli.kanban_db, fastapi, pydantic, yaml | REST API for dashboard |

---

## File System Dependencies

| Path | Purpose |
|------|---------|
| `~/.hermes/kanban.db` | Kanban task database (Hermes core) |
| `~/.hermes/state.db` | Global session database (Hermes core) |
| `~/.hermes/profiles/<name>/state.db` | Profile-specific session database |
| `~/.hermes/profiles/<name>/config.yaml` | Worker profile config |
| `~/.hermes/profiles/<name>/SOUL.md` | Worker identity |
| `~/.hermes/profiles/<name>/memories/MEMORY.md` | Worker memory |
| `~/.hermes/profiles/<name>/skills/` | Worker skills directory |
| `~/.hermes/profiles/<name>/plugins/` | Symlinked plugins (agora visible to workers) |
| `~/.hermes/agora/motions.db` | Agora motions/messages/votes/discussion_state |
| `~/.hermes/agora/projects/<name>.json` | Project registry |
| `~/.hermes/agora/workers/<name>.json` | Worker registry |
| `~/.hermes/agora/teams/<name>.json` | Team registry |
| `~/.hermes/agora/run_discussion_<motion_id>.py` | Temporary discussion driver runner script |
| `~/.hermes/scripts/leader_heartbeat.sh` | Heartbeat cron script |
| `~/.hermes/skills/collaboration/agora-awareness/` | Deployed skill |
| `~/.hermes/skills/collaboration/agora-deliberation/` | Deployed skill |
| `<workdir>/AGENTS.md` | Project context file (auto-injected by Hermes) |

---

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `HERMES_KANBAN_DB` | Kanban DB path | `~/.hermes/kanban.db` |
| `HERMES_HOME` | Hermes home directory | `~/.hermes` |
| `TERMINAL_CWD` | Working directory for agent (sets AGENTS.md context) | — |
| `HERMES_KANBAN_TASK` | Current task ID (set by dispatcher) | — |
| `HERMES_KANBAN_BOARD` | Kanban board name | — |
| `AGORA_PLUGIN_PATH` | Override plugin directory path | Auto-detected |

---

## SQLite Schemas

### `motions.db` (Agora-owned)

```sql
-- motions table
CREATE TABLE motions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'discussing',
    state TEXT DEFAULT 'discussing',
    decision TEXT,
    rationale TEXT,
    action_items TEXT DEFAULT '[]',
    current_round INTEGER DEFAULT 0,
    max_rounds INTEGER DEFAULT 3,
    source TEXT DEFAULT 'user',
    source_task_id TEXT,
    blocking INTEGER DEFAULT 0,
    participants TEXT DEFAULT '[]',
    created_at TEXT,
    closed_at TEXT,
    chair TEXT,
    max_steps INTEGER DEFAULT 30,
    step_count INTEGER DEFAULT 0,
    project TEXT
);

-- messages table
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    motion_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    stance TEXT DEFAULT 'speak',
    round_num INTEGER DEFAULT 0,
    timestamp TEXT,
    is_chair INTEGER DEFAULT 0,
    step_type TEXT DEFAULT 'speak',
    FOREIGN KEY (motion_id) REFERENCES motions(id)
);

-- discussion_state table
CREATE TABLE discussion_state (
    motion_id TEXT PRIMARY KEY,
    current_state TEXT,
    next_speaker TEXT,
    last_guidance TEXT,
    last_action TEXT,
    updated_at TEXT
);

-- votes table
CREATE TABLE votes (
    id TEXT PRIMARY KEY,
    motion_id TEXT NOT NULL,
    voter TEXT NOT NULL,
    vote TEXT,
    rationale TEXT,
    timestamp TEXT
);
```

PRAGMA: `journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON`

### `kanban.db` (Hermes core, read-only access)

Tables used: `tasks`, `task_runs`, `task_comments`, `boards`

---

## Version Compatibility

| Agora | Hermes Agent | Notes |
|-------|-------------|-------|
| v1.7.1 | v0.18+ | Post-Task Skill Review in all worker SOUL.md templates; `render_soul` appends `_POST_TASK_SKILL_REVIEW` |
| v1.7.0 | v0.18+ | Discussion speakers use `hermes-cli` toolset (full tools); chair retry on non-JSON; `agora_close_task` tool; kanban tenant filtering; `complete_count` init; researcher SOUL.md enforces tool usage |
| v1.4.x | v0.17+ | Basic plugin API, no CLI command |

Hermes backward compatibility: Agora uses try/except fallbacks for optional imports (FastAPI, memory_tool path).
