# Agora Module Dependencies

> Last updated: **v2.0.5** — generated from the source with an AST extractor, not
> maintained by hand. See [Keeping this current](#keeping-this-current) before
> editing the tables.

## Overview

Agora is a Hermes Agent plugin. Hermes loads a directory plugin as the package
**`hermes_plugins.agora`** with its own search path; nothing is installed into it
and nothing is added to `sys.path` (see [Import style](#import-style)).

What it depends on:

| Dependency | Used for | Where |
|---|---|---|
| Plugin registration API (`ctx.register_tool` / `register_hook` / `register_cli_command`) | registering 20 tools, 3 hooks, the `hermes agora` CLI | `__init__.py` |
| Kanban task database (`hermes_cli.kanban_db`) | all discussion + execution state | via `agora/kanban_compat.py` |
| Profile management (`hermes_cli.profiles`) | worker profiles in the dashboard | `dashboard/plugin_api.py` |
| `hermes_constants.get_hermes_home` | resolving the Hermes home | `agora/utils.py`, `agora/storage/motions.py` |
| The `hermes` CLI binary (subprocess) | spawning agents, cron management | `agora/discussion/agent_spawn.py`, `agora/leader_loop.py`, `agora/worker_manager.py`, `project_planner.py` |
| FastAPI + Pydantic + PyYAML | dashboard routes; reading/writing `config.yaml` | `dashboard/plugin_api.py`, `agora/utils.py`, `agora/worker_manager.py` |

**No external pip package is required beyond what Hermes already ships.** There is
no `pyproject.toml`, no `requires` entry in `plugin.yaml`, and no
`python_dependencies` — so there is no dependency floor to pin.

---

## Hermes Core API Dependencies

### Plugin registration (`ctx`)

Used once, in `__init__.py:register(ctx)`:

| Method | Purpose |
|--------|---------|
| `ctx.register_tool(name, toolset, schema, handler, …)` | 20 Agora tools. Handlers are wrapped by `_wrap_handler` (sync) / `_wrap_handler_async` (async) in `tools/__init__.py`, which serialize dict returns to JSON strings — the registry expects `str` or a multimodal dict, not a plain dict |
| `ctx.register_hook(event_name, callback)` | 3 kanban lifecycle hooks |
| `ctx.register_cli_command(name, help, setup_fn, handler_fn, …)` | the `hermes agora` subcommand |

`register()` registers only, it does not write to disk. Skill deployment is the
explicit `hermes agora setup` command.

### `hermes_cli.kanban_db` — always through the compat bridge

Every kanban call in the plugin goes through `agora/kanban_compat.py`, which
resolves symbols against the September 2026 decomposition's submodules first and
falls back to the legacy `kanban_db` attribute, so one build works on both
layouts:

| Symbol | Call sites | What it does |
|--------|-----------|--------------|
| `connect` | 27 | open a connection (**moved** → `kanban_db_connect`) |
| `get_task` | 12 | fetch a task |
| `add_comment` | 7 | write speech / votes / motion metadata as comments |
| `create_task` | 5 | create motion, execution, chat-root and assigned tasks |
| `list_comments` | 5 | read discussion history |
| `delete_archived_task` | 2 | drop a project's tasks on stop / restart |
| `Task` | 2 | reconstruct rows (status counts) |
| `add_notify_sub` | 1 | subscribe a worker to the team channel (**moved** → `kanban_db_notify`) |
| `claim_unseen_events_for_sub` | 1 | pull unread channel messages (**moved**) |
| `remove_notify_sub` | 1 | unsubscribe (**moved**) |
| `rewind_notify_cursor` | 1 | un-consume messages when a send fails (**moved**) |
| `schedule_task` | 1 | park the chat root in `scheduled` |
| `link_tasks` | 1 | parent an execution task to its motion |
| `complete_task` | 1 | `agora_close_task` action=complete |
| `archive_task` | 1 | `agora_close_task` action=cancel |
| `block_task` | 1 | block a task |
| `_append_event` | 1 | record a task event on motion close |
| `child_ids` | 1 | find a motion's execution tasks |
| `list_boards` | 1 | dashboard board picker |

**Moved-symbol bridge** (`_MOVED` in `agora/kanban_compat.py`): `connect` →
`hermes_cli.kanban_db_connect`; `add_notify_sub`, `list_notify_subs`,
`remove_notify_sub`, `claim_unseen_events_for_sub`, `unseen_events_for_sub`,
`advance_notify_cursor`, `rewind_notify_cursor` → `hermes_cli.kanban_db_notify`.

**DB path**: `HERMES_KANBAN_DB` if set, else `<hermes_home>/kanban.db`.

**Tables touched**: `tasks`, `task_comments`, `task_events`, `task_runs`,
`task_links`, `kanban_notify_subs`, `boards`.

### `hermes_cli.profiles`

Only in `dashboard/plugin_api.py`:

| Method | Purpose |
|--------|---------|
| `profiles.list_profiles()` | list profiles with config summary |
| `profiles.get_profile_dir(name)` | resolve a profile directory |
| `profiles.delete_profile(name, yes=True)` | delete a worker's profile |

### `hermes_constants`

| Function | Used in | Purpose |
|----------|---------|---------|
| `get_hermes_home()` | `agora/utils.py`, `agora/storage/motions.py` | resolve the Hermes home (context override → `HERMES_HOME` → platform default) |

Two helpers in `agora/utils.py` wrap it, and the distinction matters:

- `get_hermes_root()` — the **active** home exactly as core resolves it (may be a
  profile directory). Used for per-profile paths such as deployed skills.
- `get_global_root()` — the **global** home, unwinding `<home>/profiles/<name>`
  and honouring `HERMES_KANBAN_DB`. Used for the Agora registries, the heartbeat
  script, and the cron environment, all of which must be shared across profiles.

### Memory store — not a dependency

Agora does **not** import `tools.memory_tool` / `hermes_cli.memory_tool`. Worker
Self-Growth has two channels: **Skills** (`skill_manage`) and **SOUL.md**
(`patch`). Discussion conclusions are written to the motion task's `result`;
nothing in the plugin writes `MEMORY.md` (the file may still exist because core
maintains it per profile).

### `hermes` CLI binary

Resolved by `find_hermes_binary()` in `agora/utils.py`: `HERMES_BIN` override →
`hermes` next to `sys.executable` → `<hermes_home>/hermes-agent/venv/bin/hermes`
→ `shutil.which("hermes")`. No install layout is hardcoded.

| Command | Used in | Purpose |
|---------|---------|---------|
| `hermes -p <profile> [--yolo --accept-hooks] --toolsets terminal,file,web,skills,todo,session_search,code_execution chat -Q -q <prompt>` (`AGORA_SPEAKER_TOOLSETS` overrides the list) | `agora/discussion/agent_spawn.py` | spawn a discussion speaker. The bypass flags appear **only** when the project set `allow_unattended` |
| `hermes -p <profile> [--yolo --accept-hooks] --toolsets file,web,skills,todo,session_search,agora chat -Q -q <prompt>` | `agora/leader_loop.py` | spawn the leader for a heartbeat (restricted toolset, no terminal). Same gate |
| `hermes cron create <schedule> --name <name> --no-agent --script leader_heartbeat.sh --deliver local` | `project_planner.py` | create the heartbeat job |
| `hermes cron list --json` | `project_planner.py` | verify a job still exists |
| `hermes cron edit <job_id> --schedule <schedule>` | `project_planner.py` | change the interval |
| `hermes cron pause\|resume heartbeat-<project>` | `project_planner.py` | pause / resume the heartbeat |
| `hermes cron remove <job_id>` | `project_planner.py` | remove the job |
| `hermes profile create <name> --clone-from <src> --description <d>` | `agora/worker_manager.py` | only when cloning from an existing profile; the default path creates the profile directory itself and never shells out |

Note the direction of the `HERMES_HOME` override on these: the cron and
`profile` calls pass the **global** home explicitly so the job/registry belongs to
the gateway, not to whichever profile happened to be active.

**Worker toolsets** (written to the profile's `config.yaml` by
`_patch_config_toolsets`): `terminal, file, web, skills, todo, session_search` —
7 roles. The leader template uses `file, web, skills, todo, session_search` (no
`terminal`), and `agora` is added at spawn. No `browser`, `tts`, `vision`,
`code_execution`, `computer_use`, `cronjob`, `delegation`, `clarify`, or
`memory`.

### FastAPI + Pydantic

`dashboard/plugin_api.py` only: `APIRouter` (routes), `HTTPException` (errors),
`Query`, `BaseModel`, `Field`. The import is guarded — `APIRouter = None` when
FastAPI is absent, and the module still imports so the gateway can load the
plugin's tools without a dashboard.

### PyYAML (`yaml`)

`agora/utils.py` (`patch_config_model`), `agora/worker_manager.py`,
`dashboard/plugin_api.py` — reading and writing profile `config.yaml`. PyYAML
ships with Hermes; it is not declared as a plugin dependency.

---

## Internal Module Dependencies

### Import style

Every module reaches its siblings through **relative** imports inside the
`hermes_plugins.agora` package, e.g. `from ..agora.storage import motions_kanban`
from `tools/`, or `from .agora.utils import …` from the plugin root.

The plugin root is **never** added to `sys.path`. It contains `tools/`, `hooks/`
and `skills/`, all of which core also has, so putting it there shadows those
packages. Two consequences worth knowing:

- Modules must be imported as part of the package. A standalone
  `python3 <file>.py` will not resolve the relative imports — the generated
  heartbeat script and discussion runner therefore register the package
  (`hermes_plugins.agora` with its own `__path__`) the same way Hermes' loader
  does before importing anything from it.
- Both standalone entry points prefer `sys.executable` over a bare `python3`: on
  a managed install the latter resolves to Hermes' bundled tool Python, which
  cannot import `hermes_cli`.

### Import graph

`[M]` = imported at module level, `[l]` = imported inside a function (lazy).

```
__init__.py  (plugin root, package entry)
  [l] .tools, .hooks, .cli, .agora.utils

tools/__init__.py                    20 tools + /agora slash command
  [l] .agora.storage.motions_kanban      discussion/motion API (shim)
  [l] .agora.discussion.agent_spawn      spawn the discussion driver
  [l] .agora.discussion.roles            discussion templates
  [l] .agora.kanban_compat               board access
  [l] .agora.team_manager                role → worker routing
  [l] .agora.utils, .agora.worker_manager, .agora.worker_templates
  [l] .project_planner                   project lifecycle
  [l] .agora.execution                   (via hooks) discussion → tasks

hooks/__init__.py                    3 kanban hooks: completed, claimed, blocked
  [l] .agora.storage.motions_kanban
  [l] .agora.kanban_compat
  [l] .agora (execution), .project_planner

cli.py                               `hermes agora` subcommand
  [l] .agora.storage.motions_kanban, .agora.utils
  [l] .  (deploy_bundled_skills)

dashboard/plugin_api.py              REST routes for the dashboard
  [M] fastapi, pydantic
  [l] .agora.kanban_compat, .agora.storage.motions_kanban
  [l] .agora.team_manager, .agora.worker_manager, .agora.worker_templates
  [l] .agora.utils, .agora.discussion.agent_spawn
  [l] .project_planner
  [l] hermes_cli.profiles, yaml

project_planner.py                   project lifecycle, AGENTS.md, heartbeat cron
  [M] .agora.utils
  [l] .agora.chat, .agora.kanban_compat, .agora.leader_loop
  [l] .agora.storage.motions_kanban, .agora.team_manager, .agora.worker_manager
  [l] .  (deploy_bundled_skills)

agora/leader_loop.py                 heartbeat, stuck-motion rescue, cleanup
  [M] .utils, ..project_planner
  [l] .discussion.agent_spawn, .kanban_compat, .storage.motions_kanban
  [l] .team_manager, .worker_manager

agora/discussion/driver.py           event-driven discussion loop
  [M] .agent_spawn, .chair, ..storage.motions_kanban, ..utils, ...project_planner
  [l] .. (execution), ..kanban_compat, ..session_manager
  [l] ..team_manager, ..worker_manager

agora/team_manager.py                teams + role → worker dispatch map
  [M] .utils
  [l] .worker_manager, ..project_planner

agora/worker_manager.py              worker profile lifecycle
  [M] .utils, .worker_templates
  [l] yaml

agora/session_manager.py             session size tracking + rotation
  [l] .kanban_compat, .worker_manager

agora/storage/motions_kanban.py      1.x motions API on the kanban backend (shim)
  [l] .kanban_compat, .. (motion), ...project_planner

agora/execution.py                   discussion → execution task conversion
  [M] .kanban_compat
  [l] . (motion)

agora/motion.py                      motion lifecycle, speech, votes, close
  [M] .kanban_compat
  [l] . (chat)

agora/chat.py                        team channel: root task, messages, cursors
  [M] .kanban_compat
  [l] .kanban_compat

agora/discussion/agent_spawn.py      spawn speaker / chair / driver subprocesses
  [M] ..utils
  [l] ..utils

agora/discussion/chair.py            chair prompts (opening, evaluate, vote, summary)
agora/discussion/roles.py            discussion templates (tech_choice, …)
agora/storage/motions.py             legacy 1.x SQLite store
agora/kanban_compat.py               kanban_db bridge (no internal deps)
agora/worker_templates.py            8 role templates + SOUL.md rendering
agora/utils.py                       path resolution, binary lookup, JSON helpers
  [l] hermes_constants, yaml
```

### Cycles

There is exactly **one** mutually-dependent group — `project_planner`,
`leader_loop` and `team_manager` — and the lazy imports are what keep it
importable. Do not "tidy" one of these into a module-level import:

| Edge inside the cycle | Kind |
|-----------------------|------|
| `agora/leader_loop.py` → `project_planner` | **module level** (the only eager edge in the group) |
| `agora/leader_loop.py` → `agora/team_manager.py` | lazy |
| `agora/team_manager.py` → `project_planner` | lazy |
| `project_planner.py` → `agora/leader_loop.py` | lazy |
| `project_planner.py` → `agora/team_manager.py` | lazy |

Everything else that looks like a cycle is one-directional and lazy, so it can be
made eager safely if ever needed: `motion` → `chat`, `execution` → `motion`,
`storage/motions_kanban` → `project_planner`, `session_manager` → `worker_manager`,
`discussion/driver` → `project_planner`.

**Leaf modules** (no internal dependencies at all — the safest place to add shared
helpers): `agora/utils.py`, `agora/kanban_compat.py`, `agora/worker_templates.py`,
`agora/storage/motions.py`, `agora/discussion/chair.py`,
`agora/discussion/roles.py`.

---

## File System Dependencies

`<global>` = `get_global_root()` (never a profile directory);
`<home>` = `get_hermes_root()` (the active home, may be a profile).

| Path | Read | Written | Purpose |
|------|------|---------|---------|
| `<hermes_home>/kanban.db` | ✓ | ✓ | kanban state (via `HERMES_KANBAN_DB`) |
| `<hermes_home>/state.db` | ✓ | — | global session DB (core) |
| `<global>/agora/projects/<name>.json` | ✓ | ✓ | project registry: goal, stop condition, board, heartbeat, `chat_root_id`, `allow_unattended` |
| `<global>/agora/workers/<name>.json` | ✓ | ✓ | worker registry: role, session ids, description |
| `<global>/agora/teams/<name>.json` | ✓ | ✓ | team registry: members, role → worker map |
| `<global>/agora/run_discussion_<motion>.py` | ✓ | ✓ | generated discussion runner (one per motion) |
| `<global>/agora/discussion_<motion>.log` | — | ✓ | runner stdout/stderr |
| `<global>/agora/motions.db` | ✓ | — | **legacy 1.x store** — 2.0 never writes it (state lives on the board) |
| `<global>/scripts/leader_heartbeat.sh` | ✓ | ✓ | heartbeat cron script (rewritten when its content changes) |
| `<global>/cron/jobs.json` | ✓ | — | read to verify a heartbeat job still exists |
| `<home>/skills/collaboration/<skill>/` | — | ✓ | bundled skills, deployed by `hermes agora setup` / `agora_start_project` |
| `<home>/profiles/<name>/config.yaml` | ✓ | ✓ | worker profile config (copied from global, then toolsets/model patched) |
| `<home>/profiles/<name>/SOUL.md` | ✓ | ✓ | worker identity |
| `<home>/profiles/<name>/.env` | — | ✓ | **copy** of the global `.env`, mode `0600` |
| `<home>/profiles/<name>/skills/` | ✓ | ✓ | worker's own skills; seeded with `agora-awareness` |
| `<home>/profiles/<name>/plugins/` | — | ✓ | symlinks to global plugins so workers see Agora |
| `<home>/profiles/<name>/memories/MEMORY.md` | ✓ | — | maintained by core, not by Agora |
| `AGENTS.md` in the project workdir | ✓ | ✓ | project context, regenerated on heartbeat / motion / project changes |

---

## Environment Variables

### Read

| Variable | Read in | Purpose |
|----------|---------|---------|
| `HERMES_KANBAN_DB` | `agora/utils.py`, `agora/leader_loop.py`, `agora/session_manager.py`, `agora/storage/motions.py`, `project_planner.py`, `dashboard/plugin_api.py` | kanban DB path; also determines the global root |
| `HERMES_BIN` | `agora/utils.py` | override the `hermes` binary |
| `HERMES_KANBAN_TASK` | `tools/__init__.py` | the calling task, used to resolve its project |
| `HERMES_PROFILE` | `tools/__init__.py` | the calling profile |
| `AGORA_PLUGIN_PATH` | heartbeat script | override the plugin directory the script loads |
| `AGORA_PYTHON` | heartbeat script | override the interpreter the script uses |

`HERMES_HOME` is **never read directly** — every path goes through
`hermes_constants.get_hermes_home()` (via `get_hermes_root()` /
`get_global_root()`). That keeps the context override, the env var and the
platform default resolved in one place.

### Written into subprocess environments

| Variable | Set in | Value | Why |
|----------|--------|-------|-----|
| `HERMES_HOME` | `project_planner.py` (cron), `agora/worker_manager.py` (profile create/delete) | global home | cron jobs and the profile registry must belong to the gateway, not to whichever profile happened to be active |
| `HERMES_KANBAN_DB` | `agora/leader_loop.py` | inherited value | keep the leader on the same board |
| `HERMES_KANBAN_BOARD` | `agora/discussion/agent_spawn.py` | the project's board | route the speaker's kanban tools to the right board |
| `TERMINAL_CWD` | `agora/discussion/agent_spawn.py`, `agora/leader_loop.py` | project workdir | the agent's file tools and AGENTS.md context |

`HERMES_PROFILE` / `HERMES_KANBAN_TASK` are set by Hermes for the calling session,
not by Agora; `agora/leader_loop.py` deliberately does **not** override
`HERMES_HOME` for the leader, so `-p <profile>` keeps each profile's sessions,
skills and memory isolated.

---

## SQLite Schemas

### `motions.db` — legacy (1.x only)

> **2.0 does not read or write this database.** Discussion state lives on the
> kanban board: a motion is a task, speech/votes are `[agora:msg]` comments, and
> the conclusion is `task.result`. The schema below is kept for the legacy 1.x
> store that `agora/storage/motions.py` still serves to outside consumers.

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

### `kanban.db` (Hermes core — Agora reads and writes its own boards)

Tables used: `tasks`, `task_comments`, `task_events`, `task_runs`, `task_links`,
`kanban_notify_subs`, `boards`.

Every task Agora creates carries `tenant = "agora-<project>"`. Queries and
deletes are scoped to that tenant; a task without a tenant belongs to someone
else and is never touched.

**Board names have a single construction site**: `project_planner.agora_board_for`
(the only place the `agora-` prefix is assembled with `safe_name()` applied). Any
other construction site would disagree with the registry for project names
containing spaces or `/`, and the resulting task would fall outside the project's
scope — invisible to status counts, skipped by `stop_project`'s cleanup, and
refused by `agora_close_task`. A test enforces this (`test_board_names_have_a_single_construction_site`).

---

## Version Compatibility

| Agora | Hermes Agent | Notes |
|-------|-------------|-------|
| v2.0.4 | >= 0.20 | Catalog admission follow-up: approvals opt-in (`allow_unattended`), `.env` copied not symlinked, registration writes nothing, board-scoped task operations, relative imports with no `sys.path` insert, English README |
| v2.0.3 | >= 0.20 | Security-scan clean for the catalog (`dangerous` findings cleared) |
| v2.0.2 | >= 0.20 | Bilingual README (EN default), `plugin.yaml` manifest corrected to 20 tools |
| v2.0.1 | >= 0.20 | Post-release review fixes (session heuristic, motion `source`) |
| v2.0.0 | >= 0.20 | Discussion and execution unified on kanban: chat bus, motion threading, execution converter |
| v1.9.2 | >= 0.20 | Bridges the September `kanban_db` decomposition (`kanban_db_connect` / `_dispatch` / `_notify`) |
| v1.9.0–1.9.1 | v0.20 | All residual memory writes removed; voting gains 429 retry |
| v1.8.8 | v0.18+ | Speaker 429 retry (10× with backoff); `on_project_complete` clears the board for a clean restart |
| v1.8.6 | v0.18+ | Worker toolsets written to `config.yaml`; leader toolset without `memory` |
| v1.8.0 | v0.18+ | Motion adopted guard (no 0-step adopt); `min_steps` discussion floor; 20 fixes |
| v1.7.0 | v0.18+ | Speakers use the full `hermes-cli` toolset; `agora_close_task` added |
| v1.4.x | v0.17+ | Basic plugin API, no CLI command |

`requires_hermes: ">=0.20"` in the catalog entry reflects what 2.0 is developed
and verified against. The `kanban_compat` bridge keeps a single build working on
both sides of the September decomposition, so the floor is conservative rather
than load-bearing.

Compatibility fallbacks in the code: FastAPI/pydantic import (guarded, dashboard
only), the pre/post-decomposition `kanban_db` layout (`agora/kanban_compat.py`),
and `hermes_constants` (falls back to `~/.hermes` if core is unavailable).

---

## Keeping this current

The tables above were extracted from the source rather than transcribed. To
regenerate after a structural change:

1. **Internal imports** — walk each `*.py` with `ast`, resolve `ImportFrom.level`
   against the file's package (`hermes_plugins.agora` + the directory path, minus
   one component per extra dot), and bucket by whether the import sits at module
   level or inside a function (`ast.NodeVisitor` tracking `FunctionDef` depth).
2. **Kanban symbols** — count attribute accesses on the bridge aliases
   (`kb`, `_kb`, `_kdb`, `kanban_db`, …) and diff against `_MOVED` in
   `agora/kanban_compat.py`.
3. **Core symbol imports** — collect `ImportFrom` nodes whose module starts with
   `hermes_cli` / `hermes_constants`.
4. **Paths and environment** — collect `BinOp` `/` chains ending in a file suffix,
   and `os.environ` reads / `env[...] = …` writes.

Then re-check `hermes plugins validate` (it re-derives the declared tool and hook
surface from a live `register()` call, so a drift here shows up as a failing
admission check).
