# Agora 🏛️

> Multi-role self-driving team plugin for [Hermes Agent](https://hermes-agent.nousresearch.com) — **v1.6.0**

[中文文档](./README_CN.md)

Agora turns Hermes into a self-driving team: multiple AI roles — each a **real Hermes agent subprocess** with its own SOUL.md, MEMORY.md, tools, and session context — discuss approaches, search the web, write content, and auto-dispatch tasks. A **leader** (just a worker created from the "leader" template) acts as **chair** in event-driven discussions, dynamically picking speakers, evaluating progress, calling votes, and summarizing outcomes. Discussion results are written to the leader's MEMORY.md. The leader plans the next phase, decides when the goal is achieved, and stops itself. Everything is managed from the Dashboard — no CLI needed.

## Key Features

| Feature | Description |
|---------|-------------|
| **Unified worker model** | No separate leader concept — a leader is just a worker created from the "leader" template (`is_leader=true`). Everything goes through `worker_manager` |
| **Event-driven discussion engine** | Leader chairs discussions: opens topic, picks speakers dynamically, evaluates after each turn, calls votes, summarizes — no fixed round-robin |
| **Real agent subprocesses** | Each speaker is a real `hermes -p <profile> chat -q` spawn with SOUL.md, MEMORY.md, tools, and session context — not a stateless LLM call |
| **Per-project session isolation** | Leader uses `--resume` with project-specific `session_id` — context doesn't bleed between projects |
| **Shared experience** | Same leader profile manages multiple projects — MEMORY.md, SOUL.md, and skills are shared across projects |
| **Heartbeat on project, not profile** | `heartbeat_member`, `heartbeat_minutes`, `heartbeat_cron_id` live on the project — one leader can run different projects at different intervals |
| **AGENTS.md as single source of truth** | Project goal, stop condition, team roster (name → role template), and active discussions are written to AGENTS.md. Hermes auto-injects it into every agent's system prompt via TERMINAL_CWD. No prompt-level duplication. |
| **Mid-flight project updates** | `agora_update_project` tool lets the leader change goal, description, or stop_condition without stopping the project. AGENTS.md is refreshed automatically. `reactivate=true` restarts a completed project with a new direction. |
| **8 role templates** | Architect, Developer, Reviewer, Tester, DevOps, Researcher, Writer, Leader |
| **Self-driving** | Heartbeat cron wakes leader to check kanban, unblock, plan, dispatch |
| **Auto-stop** | Leader outputs `PROJECT_COMPLETE` when stop condition is met → **double confirmation required** → cron auto-paused |
| **3 kanban hooks** | `kanban_task_completed` (memory + comment + skill nudge), `kanban_task_claimed` (log + motion comment), `kanban_task_blocked` (auto-trigger discussion if design decision) |
| **3 bundled skills** | `agora-setup` (operator onboarding), `agora-awareness` (worker framework knowledge), `agora-deliberation` (discussion methodology) — auto-deployed to `~/.hermes/skills/collaboration/` on register |
| **Human participation** | Jump into discussions anytime via Dashboard input box |
| **Dashboard** | Projects tab (default) + Team tab (Members + Teams + Profiles sub-tabs), real-time polling, toast notifications, heartbeat control panel |
| **Generous timeouts** | All LLM calls (speak, chair, vote, dispatch) default to 1 hour (3600s). Hermes HTTP client auto-retries on timeout; Agora subprocess timeout is the hard ceiling. Tuned for local models with long context preprocessing. |

## Why Agora? — Structured Discussion Amplifies Ordinary Models

Most multi-agent frameworks assume you need a frontier model at every node. Agora challenges this assumption. In 5 hours of production monitoring (docmind project, local model via API relay — not a frontier model), we observed:

- An **Architect** correcting a **Researcher's** proposed sequencing, citing exact file paths and line numbers
- A **Developer** overriding effort estimates with concrete numbers ("2-3 hours, not days")
- A **Tester** confirming regression risk by referencing the existing 125-test suite
- A **Writer** pinpointing exactly which lines of `gap-analysis.md` needed updating

None of these outputs required any single model to hold the full decision tree in its head. Each agent only needed to make a **domain-local judgment** — and the structured discussion framework stitched them into a coherent decision.

### How the architecture compensates for model limitations

| Model weakness | Agora's structural remedy |
|----------------|--------------------------|
| **Loses focus in long context** | Each speaker sees a compact, structured history (`[role (step_type)]: content`), not raw conversation. Typical input: ~2000 chars. |
| **Jumps to conclusions** | Step-based flow forces: opening → speak → chair evaluates → next speaker. No skipping ahead. |
| **Blind spots / single perspective** | Chair explicitly checks "who hasn't spoken?" and dispatches them. All perspectives must be heard before closure. |
| **Forgets prior decisions** | Discussion outcomes are written to the leader's MEMORY.md. Next discussion starts with accumulated team knowledge. |
| **Can't self-assess when stuck** | Chair's meta-decision loop: `continue | dispatch | vote | close` — the framework asks the right question at the right time. |
| **Hallucinates without evidence** | Dispatch mode sends a worker to investigate with real tools (`web_search`, `read_file`, `terminal`) before committing to an opinion. |

### The chair role is different

Speakers do **domain reasoning** ("should we use SQLite or PostgreSQL?") — single-hop, structured input, within their expertise. The chair does **meta-reasoning** ("has everyone spoken? are there unresolved disagreements? is this ready to close?") — multi-hop, requires tracking global state.

**Recommendation:** If budget is constrained, use your strongest available model for the Leader/Chair, and cheaper models for the other roles. The architecture's structural constraints — turn-taking, guided prompts, cross-validation — compensate for weaker speakers. But the chair's meta-cognitive load benefits from a more capable model.

## Install

```bash
hermes plugins install yzy806806/agora
hermes plugins enable agora
hermes gateway restart
hermes dashboard restart  # if dashboard is running
```

> **Note:** Both the gateway **and** the dashboard need restarting after enabling.
> The gateway loads plugin tools/hooks; the dashboard discovers plugin sidebar
> tabs at startup. If you only restart the gateway, the Agora tab won't appear
> in the dashboard sidebar.

## Quick Start

### Option A: Conversational setup (no dashboard needed)

Just tell Hermes: *"Install the Agora plugin and set up a development team."*

Hermes reads the `agora-setup` skill and handles the full flow:
1. `agora_list_templates()` — see available roles
2. `agora_create_worker(name="leader", role="leader")` — create workers
3. `agora_create_team(team_name="alpha", workers=[...])` — form a team
4. `agora_start_project(name="my-project", workdir="/path/to/repo", goal="...", stop_condition="...")` — start

### Option B: Dashboard setup

Open `hermes dashboard`, go to the **Agora** tab → **Team → Members**:

1. Pick a template, give the worker a name (e.g. `alice`, `bob`)
2. Create as many workers as you need — including a leader (from the "leader" template)
3. Go to **Team → Teams** — select workers, form a team

**Templates:**

| Template | Icon | Role |
|----------|------|------|
| Architect | 🏗️ | System design, API contracts, tech selection |
| Developer | 💻 | Implementation, testing, dependencies |
| Reviewer | 🔍 | Code review, security, edge cases |
| Tester | 🧪 | Test strategy, automation, bug reporting |
| DevOps | 🚀 | CI/CD, deployment, infrastructure |
| Researcher | 🔎 | Web research, trend analysis, information synthesis |
| Writer | ✍️ | Content writing, structuring, tone |
| Team Leader | 👨‍💼 | Project monitoring, phase planning, completion detection |

### Start a project

In the **Projects** tab, click "Start Project":
- **Name** (e.g. `docmind`)
- **Goal** (e.g. "持续开发docmind")
- **Stop condition** (e.g. "易用性与性能达到最优，对比同类项目，功能无缺失")
- **Working directory**
- **Team** — select the team you formed
- **Heartbeat member** — select a leader worker
- **Heartbeat interval** — minutes (default: 15)

### Update project mid-flight

The leader can change direction without stopping:

```python
agora_update_project(
    name="docmind",
    goal="Add multi-tenant support and REST API v2",
    stop_condition="All v2 API endpoints tested and documented",
    reactivate=True  # restart if project was completed
)
```

AGENTS.md is refreshed automatically — all workers see the new goal on next spawn.

## AGENTS.md — Single Source of Truth

AGENTS.md is auto-generated in the project workdir. Hermes auto-loads it into every agent's system prompt (leader, discussion participants, and kanban workers) via `TERMINAL_CWD` context file scanning.

**Contents:**
- Project name, goal, status, description
- Stop condition
- Team members table: `| Profile Name | Role (Template) |`
- Active discussions list
- Workflow instructions

**Refreshed on (atomic write — temp file + os.replace):**
- `start_project`
- Leader heartbeat
- `agora_update_project`
- Motion create (`agora_raise_motion`)
- Motion close (`agora_close_motion`)

**Heartbeat prompt** is minimal — just a wake-up call. All context comes from AGENTS.md, not prompt injection.

## Tools (17)

| Tool | Description |
|------|-------------|
| `agora_raise_motion` | Start a team discussion |
| `agora_get_messages` | Read discussion messages |
| `agora_get_result` | Get closed discussion result |
| `agora_list_motions` | List active/closed discussions |
| `agora_close_motion` | Close a stale/resolved motion |
| `agora_create_task` | Create a kanban task |
| `agora_start_project` | Start a self-driving project |
| `agora_stop_project` | Stop a project |
| `agora_project_status` | Check project status |
| `agora_update_project` | Update goal/stop_condition mid-flight |
| `agora_create_worker` | Create a worker from template |
| `agora_list_workers` | List all workers |
| `agora_remove_worker` | Remove a worker |
| `agora_list_templates` | List role templates |
| `agora_create_team` | Create a team |
| `agora_list_teams` | List teams |
| `agora_remove_team` | Remove a team |

> **Note:** All tool handlers return JSON strings (auto-serialized via `_wrap_handler` / `_wrap_handler_async`). Hermes tool registry requires `str`, not `dict`.

## Kanban Hooks

| Hook | When | Action |
|------|------|--------|
| `kanban_task_completed` | Worker finishes a task | Write motion result to leader's memory (not workers); if complex task (>1 run or >30min), write skill-creation nudge comment |
| `kanban_task_claimed` | Dispatcher assigns a task | Log claim; inject motion decision as task comment |
| `kanban_task_blocked` | Worker blocks a task | If reason mentions "design decision" or "motion" → auto-create discussion |

## Timeout Configuration

All LLM-related timeouts default to **1 hour (3600s)**:

| Scenario | Default | Notes |
|---|---|---|
| Speaker发言 (`speak_timeout`) | 3600s | Worker spawned to discuss |
| Chair评估 (`chair_timeout`) | 3600s | Leader evaluates discussion state |
| Dispatch/调研 | 3840s | `speak_timeout + 240s` buffer |
| 投票 | 3600s | Same as speak_timeout |
| `spawn_agent_speak` | 3600s | Function default |
| `spawn_chair_speak` | 3600s | Function default |

Hermes HTTP client auto-retries on timeout. Agora subprocess timeout is the hard ceiling — if exceeded, the worker is marked as failed and the discussion continues.

## Architecture

```
agora/
├── plugin.yaml                  # Plugin manifest (17 tools + hooks)
├── __init__.py                  # register(ctx)
├── tools/__init__.py            # 17 tool definitions + _wrap_handler
├── cli.py                       # hermes agora CLI
├── hooks/__init__.py            # 3 kanban hooks
├── project_planner.py           # Project lifecycle + heartbeat + AGENTS.md (atomic)
├── agora/
│   ├── utils.py                 # Shared utilities
│   ├── discussion/
│   │   ├── driver.py            # DiscussionDriver (speak/chair/vote/dispatch)
│   │   ├── agent_spawn.py       # Spawn Hermes agent subprocesses (3600s timeout)
│   │   ├── chair.py             # Chair prompts + speaker prompt builder
│   │   └── roles.py             # Discussion templates
│   ├── storage/motions.py       # SQLite storage (WAL + busy_timeout=5000)
│   ├── session_manager.py       # Session size tracking + rotation (profile-specific state.db)
│   ├── worker_templates.py      # 8 role templates (SOUL.md rendering)
│   ├── worker_manager.py        # Worker lifecycle (fcntl-locked sessions)
│   ├── team_manager.py          # Team + dispatch routing
│   └── leader_loop.py           # Heartbeat + stuck motion rescue + stale state cleanup
├── dashboard/                   # Web UI + REST API
│   ├── plugin_api.py            # FastAPI routes
│   └── dist/                    # Compiled React frontend
└── skills/
    ├── agora-setup/             # Operator onboarding guide
    ├── agora-awareness/         # Worker framework knowledge
    └── agora-deliberation/      # Discussion methodology
```

## License

MIT

## Changelog

### v1.6.0 — Reactivate fix: reset completion state + heartbeat prompt

- **Reactivate now resets `complete_count`, `leader_session_id`, `completion_check_pos`** — Previously, reactivating a completed project left stale completion state. Leader would read old memory, see complete_count > 0, and immediately output PROJECT_COMPLETE without evaluating the new goal.
- **Heartbeat prompt warns about goal changes** — Added "If the goal or stop condition has changed since your last heartbeat, treat this as a NEW project phase. Do NOT carry over previous PROJECT_COMPLETE decisions."
- **Reactivate verifies cron job existence** — Checks `hermes cron list` to detect stale cron IDs (deleted during PROJECT_COMPLETE but still in project JSON).
- **`start_project` preserves existing project data** — No longer overwrites all fields when project already exists (from v1.5.9, now also in reactivate path).
- **Schema expanded** — `agora_start_project` now accepts `description`, `stop_condition`, `team`. `workdir` no longer required for existing projects.
- **Verified end-to-end** — Reactivated docmind project with new goal, leader correctly identified new phase, raised motions, team discussed and adopted, tasks being assigned.

### v1.5.9 — Fix start_project overwriting existing project data

- **`agora_start_project` no longer overwrites existing projects** — if a project already exists, it preserves all fields (team, goal, stop_condition, heartbeat_member, etc.) and only reactivates. Previously, calling `start_project` on an existing project would reset everything to defaults.
- **Schema expanded** — added `description`, `stop_condition`, `team` parameters. `workdir` is no longer required (preserved from existing project). All new params only override if non-empty.
- **Heartbeat cron auto-recreated** — if a reactivated project has `heartbeat_member` but no `heartbeat_cron_id`, the cron job is automatically recreated.

### v1.5.8 — Dashboard project settings UI

- **Project Settings panel** in dashboard Overview tab — edit goal and stop_condition inline, reactivate completed/stopped projects with one click. Calls `PUT /api/plugins/agora/projects/{name}`.
- Added `agora-form-field` and `agora-input` CSS classes.

### v1.5.7 — Hermes v0.18.2 compatibility fix

- **`kanban_db.add_comment` signature changed** — now requires `author` parameter. Updated all 3 call sites in hooks.
- Compatibility verified against Hermes v0.18.2 (2026.7.7.2):
  - `ctx.register_tool` / `register_hook` / `register_cli_command` — unchanged ✅
  - kanban hooks (claimed/completed/blocked) — still in VALID_HOOKS ✅
  - `_normalize_handler_result` requires str — Agora uses `_wrap_handler` ✅
  - `Task` class fields (tenant, body, assignee, started_at, completed_at) — unchanged ✅
  - `create_task` / `block_task` / `get_task` — backward compatible ✅
  - AGENTS.md context file loading — unchanged ✅

### v1.5.6 — Timeout unification + tool handler fix + dashboard emoji + onboarding

- **All LLM timeouts unified to 1 hour (3600s)** — speak_timeout, chair_timeout, vote, dispatch, spawn defaults. Removed `min(speak_timeout, 240)` cap. Local models with long context preprocessing need generous timeouts.
- **Tool handler return type fix** — Hermes registry requires `str` (JSON), not `dict`. Added `_wrap_handler` / `_wrap_handler_async` at module level. All 17 tools now register and return correctly.
- **Dashboard emoji encoding** — JS byte escapes (`\xF0\x9F`) → Unicode escapes (`\uXXXX`). Fixed garbled `ð` → `👑`.
- **agora-setup skill** — New onboarding skill for operators (step-by-step: create workers, form teams, start projects).
- **Dead code cleanup** — Removed `_build_active_motions_summary()` (superseded by AGENTS.md).

### v1.5.2 — AGENTS.md as single source of truth + project updates

- **AGENTS.md** now contains: goal, stop_condition, team members (name → role template), active discussions. Written atomically (temp + rename). Refreshed on: start_project, heartbeat, project update, motion create/close.
- **Heartbeat prompt simplified** — 6 lines, no more inline context injection. All context via AGENTS.md auto-load.
- **`agora_update_project` tool** — change goal/stop_condition mid-flight. `reactivate=true` restarts completed projects.
- **Motion memory cleanup** — decision records only written to leader's MEMORY.md, not workers. Workers keep their own technical experience.
- **Skill creation nudge** — complex tasks (>1 run or >30min) get a kanban comment prompting the worker to save reusable workflows.
- **17 tools** (added `agora_update_project`).

### v1.4.4–v1.4.6 — Code audit fixes

- Chair prompt: prevent false truncation calls
- Driver: MAX_SAME_SPEAKER=2 hard limit
- `_has_pending_tasks()` now accepts project_name with tenant filter
- SQLite busy_timeout=5000 for concurrent safety
- `_find_project_for_task()` uses task.tenant instead of string matching
- Worker session JSON uses fcntl.flock for concurrent safety
- Stale discussion_state cleanup on every heartbeat
- Session manager queries profile-specific state.db
- 15 issues fixed across 3 releases

### v1.4.3 — Discussion state consistency and stale motion recovery

- `discussion_state` cleaned on close
- Stuck discussions with messages recovered
- `agora_close_motion` tool added
- Speaker session preserved on timeout
- Timeout increased (900s/300s)

### v1.4.0–v1.4.2 — Discussion engine reliability

- Session-not-found recovery
- Empty tool argument handling
- Stale memory poisoning fix
- Dead session cleanup
- Code cleanup and hardcoded path fixes

### v1.3.0 — Discussion engine critical fixes

- Leader and participants now get `--toolsets agora`
- Stuck motion recovery via `_rescue_stuck_motions()`
