# Agora 🏛️

> Multi-role self-driving team plugin for [Hermes Agent](https://hermes-agent.nousresearch.com) — **v1.4.2**

[中文文档](./README_CN.md)

Agora turns Hermes into a self-driving team: multiple AI roles — each a **real Hermes agent subprocess** with its own SOUL.md, MEMORY.md, tools, and session context — discuss approaches, search the web, write content, and auto-dispatch tasks. A **leader** (just a worker created from the "leader" template) acts as **chair** in event-driven discussions, dynamically picking speakers, evaluating progress, calling votes, and summarizing outcomes. Discussion results are written to each participant's MEMORY.md. The leader plans the next phase, decides when the goal is achieved, and stops itself. Everything is managed from the Dashboard — no CLI needed.

## Key Features

| Feature | Description |
|---------|-------------|
| **Unified worker model** | No separate leader concept — a leader is just a worker created from the "leader" template (`is_leader=true`). Everything goes through `worker_manager` |
| **Event-driven discussion engine** | Leader chairs discussions: opens topic, picks speakers dynamically, evaluates after each turn, calls votes, summarizes — no fixed round-robin |
| **Real agent subprocesses** | Each speaker is a real `hermes -p <profile> chat -q` spawn with SOUL.md, MEMORY.md, tools, and session context — not a stateless LLM call |
| **Per-project session isolation** | Leader uses `--resume` with project-specific `session_id` — context doesn't bleed between projects |
| **Shared experience** | Same leader profile manages multiple projects — MEMORY.md, SOUL.md, and skills are shared across projects |
| **Heartbeat on project, not profile** | `heartbeat_member`, `heartbeat_minutes`, `heartbeat_cron_id` live on the project — one leader can run different projects at different intervals |
| **Team awareness** | `AGENTS.md` auto-generated in project workdir — workers and leader can see team members, roles, and project context. Refreshed on heartbeat and on `kanban_task_claimed` |
| **Memory persistence** | Discussion decisions and action items written to each participant's MEMORY.md for accumulated team knowledge |
| **8 role templates** | Architect, Developer, Reviewer, Tester, DevOps, Researcher, Writer, Leader |
| **Self-driving** | Heartbeat cron wakes leader to check kanban, unblock, plan, dispatch |
| **Auto-stop** | Leader outputs `PROJECT_COMPLETE` when goal achieved → **double confirmation required** (2 consecutive signals) → cron auto-paused |
| **3 kanban hooks** | `kanban_task_completed` (memory + comment write-back), `kanban_task_claimed` (log + AGENTS.md refresh), `kanban_task_blocked` (auto-trigger discussion if design decision) |
| **Bundled skills** | Plugin ships with `agora-awareness` and `agora-deliberation` skills — auto-deployed to `~/.hermes/skills/collaboration/` on register, seeded into every new worker's profile |
| **Human participation** | Jump into discussions anytime via Dashboard input box |
| **Dashboard** | Projects tab (default) + Team tab (Members + Teams + Profiles sub-tabs), real-time polling, toast notifications, heartbeat control panel |

## Install

```bash
hermes plugins install yzy806806/agora
hermes plugins enable agora
hermes gateway restart
hermes dashboard restart  # if dashboard is running — plugin's sidebar tab won't appear until restart
```

> **Note:** Both the gateway **and** the dashboard need restarting after enabling.
> The gateway loads plugin tools/hooks; the dashboard discovers plugin sidebar
> tabs at startup. If you only restart the gateway, the Agora tab won't appear
> in the dashboard sidebar.

## Quick Start

### 1. Create workers from Dashboard

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

Each worker is a Hermes profile with: `config.yaml` (cloned from parent), `SOUL.md` (from template), `memories/MEMORY.md`, `memories/USER.md`, `skills/`. Workers persist across projects — their memory, skills, and identity carry over, just like a real employee.

### 2. Start a project

In the **Projects** tab, click "Start Project":
- **Name** (e.g. `fashion-report`)
- **Goal** (e.g. "Write a 2026 spring/summer fashion trends PDF")
- **Working directory**
- **Team** — select the team you formed
- **Heartbeat member** — select a leader worker to wake on heartbeat
- **Heartbeat interval** — minutes between heartbeats (default: 15)
- Click create

The heartbeat cron is created automatically. `AGENTS.md` is written to the project workdir so all workers see team context.

### 3. Observe and participate

Click into a project to see:
- **Overview** — progress stats (todo/running/blocked/done)
- **Kanban** — real-time task board with assignees
- **Discussions** — event-driven discussion flow: chair guidance, speaker turns, votes, and summary + input box for human participation
- **Team** — member status (idle/working)

### 4. Leader self-driving

Each heartbeat, the leader:
1. Checks blocked tasks → unblock/split/reassign
2. Checks triaged/failed tasks → analyze, fix, re-queue
3. All done → plan next phase from goal, create tasks directly
4. Direction decision needed → raise motion for team discussion
5. Goal achieved → output `PROJECT_COMPLETE` → cron auto-paused

The chair for discussions auto-resolves from `project.heartbeat_member`.

## Event-Driven Discussion Engine

Each discussion is a **real meeting of real agents**:

### How it works

```
1. Chair (Leader) opens   → states topic, names first speaker + guiding question
2. Speaker speaks         → real Hermes agent subprocess (hermes -p <profile> chat -q)
                             with SOUL.md, MEMORY.md, tools, and --resume session context
3. Chair evaluates        → continue? vote? close? (JSON-based meta-decisions)
4. Repeat 2-3             → until close or max_steps (default 30)
5. (Optional) Vote        → each participant votes → chair decides outcome
6. Summary                → chair generates action items + writes to each participant's MEMORY.md
```

### Key design decisions

| Aspect | Implementation |
|--------|---------------|
| **Speaker spawns** | `hermes -p <profile> --yolo chat -q` — a full agent with tools, memory, and identity |
| **Session continuity** | Workers use `--resume <session_id>` to carry conversation context across kanban tasks and discussions |
| **Per-project isolation** | Leader has separate `session_id` per project — context doesn't bleed, but MEMORY.md/skills are shared |
| **Chair (Leader)** | Stateless meta-caller — evaluates discussion state, picks next speaker, calls votes. No `--resume` needed |
| **Chair auto-resolve** | If `chair_profile` is omitted, auto-resolved from `project.heartbeat_member` |
| **Role identity** | Comes from each worker's SOUL.md (including the **Discussion Protocol** section) |
| **Leader SOUL.md** | Includes **Heartbeat Protocol** + **Chair Protocol** sections |
| **Memory persistence** | Discussion decisions + action items written to each participant's MEMORY.md |
| **Config inheritance** | Worker profiles inherit root `config.yaml` (compression, approvals, etc.) |

### Human participation

The Dashboard discussion view shows the full event-driven flow: chair opening, speaker turns with guidance, vote calls, and final summary. A human can type into the discussion input box at any time — the message becomes part of the discussion history that the chair and speakers see.

## Team Awareness (AGENTS.md)

An `AGENTS.md` file is auto-generated in the project workdir. Hermes auto-loads it into every worker's system prompt, giving them awareness of:
- Project name, goal, and status
- Heartbeat member and interval
- Team members table (name → role)
- Workflow instructions (kanban check, task completion, blocking, raising motions)

**Refreshed on:**
- `start_project` (initial write)
- Leader heartbeat (members may have been added/removed)
- `kanban_task_claimed` hook (before worker spawns)

## Kanban Hooks

| Hook | When | Action |
|------|------|--------|
| `kanban_task_completed` | Worker finishes a task | Write discussion result as comment + memory entry; if no pending tasks remain, signal leader |
| `kanban_task_claimed` | Dispatcher assigns a task (before worker spawns) | Log claim; refresh `AGENTS.md`; inject motion decision as task comment if applicable |
| `kanban_task_blocked` | Worker blocks a task | If reason mentions "design decision" or "motion" → auto-create a discussion motion; otherwise log for leader |

## Dashboard Structure

| Tab | Content |
|-----|---------|
| **Projects** (default) | Project list, start new project (with heartbeat config), project detail (overview/kanban/discussions/team) |
| **Team** | **Members** sub-tab (unified Workers + Leaders) / **Teams** sub-tab (team management) / **Profiles** sub-tab (profile config — model/SOUL.md/skills) |

## Configuration

`~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - agora
  entries:
    agora:
      enabled: true
      agora:
        discussion:
          max_rounds: 3
          consensus_threshold: 0.7
          max_steps: 30           # event-driven: max speaker turns before forced close
```

## Architecture

```
agora/
├── plugin.yaml                  # Plugin manifest (tools + hooks)
├── __init__.py                  # register(ctx) — 18 tools + dashboard API + CLI + 3 hooks
├── tools/__init__.py            # 18 tool definitions (unified: POST /workers only)
├── cli.py                       # hermes agora CLI
├── hooks/__init__.py            # 3 kanban hooks: completed, claimed, blocked
├── project_planner.py           # Project lifecycle + heartbeat config + AGENTS.md generation
├── agora/
│   ├── utils.py                 # Shared utilities
│   ├── discussion/              # Event-driven discussion engine
│   │   ├── driver.py            #   DiscussionDriver: chair → speakers → evaluate → close
│   │   ├── agent_spawn.py       #   Spawn real Hermes agent subprocesses (hermes -p chat -q)
│   │   ├── chair.py             #   Chair (Leader) prompts: open, evaluate, vote, summary
│   │   └── roles.py             #   Consensus checker + discussion templates
│   ├── storage/                 # SQLite storage
│   ├── session_manager.py       # Per-project session tracking + rotation
│   ├── worker_templates.py      # 8 role templates (SOUL.md rendering)
│   ├── worker_manager.py        # Worker lifecycle — unified (leader = worker with leader template)
│   ├── team_manager.py          # Team + dispatch routing
│   └── leader_loop.py           # Heartbeat spawn + PROJECT_COMPLETE detection
├── dashboard/                   # Web UI + REST API
└── skills/
    ├── agora-awareness/         # Framework overview — every worker gets this
    └── agora-deliberation/      # Discussion methodology — when/how to raise motions
```

## License

MIT

## Changelog

### v1.4.2 — Code cleanup and hardcoded path fixes

- **Version sync** — `__init__.py` `__version__` was stuck at `1.0.0`; now matches `plugin.yaml`.
- **Tool count** — Registration log said "18 tools" but there are 15.
- **Removed dead code** — Deleted `leader_manager.py` (deprecated shim, zero callers), `increment_round()` in `storage/motions.py` (unused, replaced by `step_count`), `list_available_templates()` in `worker_manager.py` (alias for `list_templates()`).
- **Removed e2e test files** — `e2e_test.py`, `e2e_test_v2.py`, `e2e_dom_inspect.py` were development artifacts with hardcoded passwords.
- **Fixed hardcoded paths** — `dashboard/plugin_api.py` had two `/root/.hermes/kanban.db` literals; now uses `HERMES_KANBAN_DB` env var with `Path.home()` fallback. `project_planner.py` heartbeat script search path now tries `$HOME` before `/root`.

### v1.4.1 — Worker profile plugin inheritance

Workers spawned with `-p <profile>` have `HERMES_HOME` pointing at their profile directory, so Hermes only scans `<profile>/plugins/` during plugin discovery — global plugins installed in `~/.hermes/plugins/` are invisible. This meant workers couldn't see Agora tools (`agora_raise_motion`, `agora_create_task`, etc.) even though the plugin was enabled in config.

**Fix:** `create_worker()` now symlinks every plugin from the global `~/.hermes/plugins/` into the profile's `plugins/` directory at creation time. Uses symlinks so global plugin updates are reflected immediately.

Also added `agora_create_task` to `provides_tools` in `plugin.yaml` (was missing from the manifest).

### v1.4.0 — Discussion engine reliability

The discussion engine now reliably completes full discussion cycles. Four root causes were fixed, verified with 3 successful end-to-end discussions (2 adopted, 1 rejected).

**Fixes:**

1. **Session-not-found recovery** — After session DB cleanup, worker registry still held stale `session_id`s. The discussion driver kept passing `--resume <dead-session>` to `hermes chat`, causing 3 consecutive dispatch failures → forced `no_consensus`. Now `agent_spawn.py` detects "Session not found" and automatically retries without `--resume` (creates a fresh session). `driver.py` also clears the worker's stale session on dispatch/speak failure.

2. **Empty tool arguments from LLM** — `glm5.2` sometimes called `agora_raise_motion` with empty `{}` arguments, ignoring the `required: ["title"]` schema. The schema `description` fields now explicitly say "REQUIRED. Provide a concise title…". Leader SOUL.md includes a concrete call example and "Do NOT use the CLI — always call the tool directly".

3. **Stale memory poisoning** — Leader's MEMORY.md had recorded "Agora plugin tools have empty schemas — use hermes kanban CLI instead", a self-reinforcing error that caused all subsequent heartbeats to skip the discussion engine entirely. Corrected to "Agora tools are functional — always provide title parameter".

4. **Driver doesn't clear dead sessions** — Added `_clear_worker_session()` to `DiscussionDriver`. On dispatch failure or empty reply, the worker's `session_id` is set to `None` in the registry so the next spawn creates a new session instead of reusing the dead one.

**Verification — 3 complete discussions:**

| # | Motion | Steps | Decision |
|---|--------|-------|----------|
| 1 | Auth vs search-filter priority | 3 | adopted (3/3) |
| 2 | Jinja2 vs frontend framework | 3 | adopted (2 adopt + 1 abstain) |
| 3 | Alembic vs hand-rolled migrations | 0 | rejected (unanimous) |

### v1.3.0 — Discussion engine critical fixes

1. **Leader had no Agora tools** — `leader_loop.py` spawned the leader without `--toolsets agora`.
2. **Participants had no Agora tools** — `agent_spawn.py` spawned workers without `--toolsets agora`.
3. **Motions stuck at round 0** — `kanban_task_blocked` hook created motions without resolving chair/participants.
4. **No recovery for stuck motions** — Added `_rescue_stuck_motions()` to `leader_loop.py`.

### v1.2.0 — Dashboard project management + form fields

### v1.1.0 — Discussion engine infinite loop fix
