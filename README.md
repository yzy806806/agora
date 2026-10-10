# Agora 🏛️

> Multi-role self-driving team plugin for [Hermes Agent](https://hermes-agent.nousresearch.com) — **v2.0.11**

[中文](./README.CN.md) | **English**

Agora turns Hermes into a self-driving team: multiple AI roles — each a **real Hermes agent subprocess** with its own SOUL.md, tools, and session context — discuss approaches, search the web, write content, and auto-dispatch tasks. A **leader** (just a worker created from the "leader" template) acts as **chair** in event-driven discussions, dynamically picking speakers, evaluating progress, calling votes, and summarizing outcomes.

**What changed in v2.0: discussion and execution are unified on Kanban.** A discussion (motion) is a sub-task of the team-channel root task; speech and votes are `[agora:msg]` comments; the conclusion is written to `task.result`; and adopted conclusions **become execution tasks automatically** (parent = that motion, so context flows in via Hermes' native parent handoff). No separate discussion database, and no leader transcription.

---

## Prerequisites

- **Hermes Agent installed and working** (v0.20.x or newer recommended)
- **A model / provider configured** — each worker profile gets its own copy of the global `config.yaml` and `.env` when it is created, so no per-worker setup is needed; you can still pin a different model per worker in the Dashboard
- **The gateway running** — the kanban dispatcher lives in the gateway; it dispatches tasks and spawns workers. Check with `hermes gateway status`
- **A project working directory** — the path to your repo (created automatically if missing)

## Install

```bash
hermes plugins install yzy806806/agora
hermes plugins enable agora
hermes agora setup         # deploy the bundled worker skills
hermes gateway restart
hermes dashboard restart   # if the dashboard is running
```

> **Note: restart BOTH the gateway and the dashboard.**
> The gateway loads the plugin's tools and hooks; the dashboard only discovers plugin sidebar tabs at startup. If you restart only the gateway, the Agora tab will not appear in the dashboard.

> **Note: `hermes agora setup` deploys the bundled worker skills** into
> `~/.hermes/skills/collaboration/`. Installing the plugin never writes to disk
> on its own; starting a project also deploys them, so the command is only
> needed if you want the skills in place beforehand.

### Approvals and unattended operation

Workers and the leader run as `hermes -p <profile> chat -Q -q` subprocesses. A
`-q` invocation has nobody present to answer an approval prompt, so **without
the bypass flag a worker's flagged actions fail closed** — it can read, search,
discuss and plan, but its file writes and shell commands are denied.

By default Agora does **not** pass the bypass:

```python
agora_start_project(name="my-project", workdir="/path/to/repo", goal="...")
# workers run with approvals enforced — safe, but they cannot implement
```

To let the team actually write code unattended, opt the project in explicitly:

```python
agora_start_project(..., allow_unattended=True)
```

That adds `--yolo --accept-hooks` to every worker/leader subprocess for that
project, meaning their file writes and shell commands execute without prompting.
Enable it only for a working directory you are willing to let agents modify
unattended. The flag lives in the project registry (`allow_unattended`) and can
be turned on later by restarting the project with `allow_unattended=True`.

---

## Quick Start

### Option A: Conversational setup (no dashboard needed)

Just tell Hermes: *"Install the Agora plugin and set up a development team."*

Hermes reads the `agora-setup` skill and handles the full flow:

1. `agora_list_templates()` — see available roles
2. `agora_create_worker(name="leader", role="leader")` — create workers
3. `agora_create_team(team_name="alpha", workers=[...])` — form a team
4. `agora_start_project(name="my-project", workdir="/path/to/repo", goal="...", stop_condition="...")` — start

### Option B: Dashboard setup

Open `hermes dashboard` → **Agora** tab → **Team → Members**:

1. Pick a template, give the worker a name (e.g. `alice`, `bob`)
2. Create as many workers as you need — **including a leader** (from the "leader" template)
3. Go to **Team → Teams** — select workers, form a team

**Role templates:**

| Template | Icon | Responsibility |
|----------|------|----------------|
| Team Leader | 👑 | Project management, discussion chair, completion detection (required) |
| Architect | 🏗️ | System design, API contracts, tech selection |
| Developer | 💻 | Implementation, testing, dependencies |
| Reviewer | 🔍 | Code review, security, edge cases |
| Tester | 🧪 | Test strategy, automation, bug reporting |
| DevOps | 🚀 | CI/CD, deployment, infrastructure |
| Researcher | 🔎 | Web research, trend analysis, information synthesis |
| Writer | ✍️ | Content writing, structuring, tone |

### Start a project

In the **Projects** tab, click "Start Project":

| Field | Meaning | Example |
|-------|---------|---------|
| **Name** | Short project name | `myapp` |
| **Goal** | High-level goal (one line) | "Ship a REST API with auth and pagination" |
| **Stop condition** | Natural-language completion criteria; the team votes on it | "All endpoints tested and documented" |
| **Working directory** | Absolute path to the repo | `/home/me/myapp` |
| **Team** | The team you formed above | `alpha` |
| **Heartbeat member** | The leader worker | `leader` |
| **Heartbeat interval** | Wake-up interval in minutes (default 15) | `15` |

---

## What to Expect Once It's Running

**This is the step people most often misjudge — read it before deciding the project is broken.**

| When | What you should see |
|------|---------------------|
| **Immediately** after starting | The project appears in the Projects tab with status `active`; AGENTS.md is written into the working directory |
| **Within one heartbeat interval** (15 min by default) | The leader wakes for the first time, reads AGENTS.md, checks kanban, then creates tasks or raises a discussion |
| After that | Tasks appear on the kanban board; the dispatcher spawns the matching role's worker to execute |
| When a discussion runs | The Agora tab shows the discussion thread; the team channel carries `[agora:msg]` messages |

> ⚠️ **The most common false alarm:** nothing happening for the first few minutes is **normal** — the leader is only woken at heartbeat time, which defaults to 15 minutes. To see action sooner, lower the heartbeat interval (e.g. 2 minutes), or click "Trigger" once in the Projects tab.

**How to confirm it's actually running:**

```
agora_project_status(name="myapp")     # project state, round, heartbeat time
hermes cron list                        # should show the heartbeat-myapp job
hermes gateway status                   # is the dispatcher running?
hermes kanban list                      # the task list
```

## Monitoring

```
# Project state
agora_project_status(name="myapp")

# Discussions
agora_list_motions(status="active")
agora_get_result(motion_id="t_xxx")
agora_get_messages(motion_id="t_xxx")

# Team channel (new in 2.0)
agora_read_chat(project="myapp", limit=20)
```

Or just open the Dashboard: `hermes dashboard` → **Agora** tab (Projects / Team, real-time polling).

## Stop & Cleanup

```
agora_stop_project(name="myapp")
```

Stopping a project pauses the heartbeat cron, sets status to `stopped`, and **deletes all of that project's kanban tasks** — a clean slate, so a restart won't see the previous round's leftovers.

Natural completion (the leader emitting `PROJECT_COMPLETE` twice in a row) performs the same cleanup.

> The heartbeat cron is **paused**, not deleted, on completion; its script stays at `~/.hermes/scripts/leader_heartbeat.sh` and is reused when you reactivate the project.

## Troubleshooting

| Symptom | Where to look |
|---------|---------------|
| Nothing happens for a long time | The heartbeat hasn't fired yet (15 min default). Check `hermes cron list` for `heartbeat-<project>`; or Trigger manually |
| Workers never pick up tasks | The gateway isn't running → `hermes gateway status`. The dispatcher lives in the gateway; without it nothing spawns workers |
| Discussions never start | `agora_list_motions(status="active")` — is it stuck at 0 steps? The leader heartbeat auto-rescues stuck motions |
| No Agora tab in the dashboard | You restarted only the gateway → `hermes dashboard restart` |
| Worker says "No inference provider configured" | The global model config is missing, or its `.env` never reached the profile. Check `~/.hermes/.env` and `~/.hermes/profiles/<name>/.env` (the plugin copies it at worker creation; re-create the worker to refresh) |
| Workers keep crashing with 429/503 in the log | API rate limiting. Add `api_max_retries` (e.g. 50) to the worker profile, or globally `hermes config set agent.api_max_retries 50` |
| "Unknown toolsets: agora" in the heartbeat log | A cosmetic ordering warning (CLI validation runs before plugin discovery finishes). Tools work fine — ignore it |

More detail in the `agora-setup` skill's Troubleshooting section.

---

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
| **Loses focus in long context** | Each speaker sees a compact, structured history (`[role (step_type)]: content`), not raw conversation. Typical input: ~2000 chars |
| **Jumps to conclusions** | Step-based flow forces: opening → speak → chair evaluates → next speaker. No skipping ahead |
| **Blind spots / single perspective** | The chair explicitly checks "who hasn't spoken?" and dispatches them. All perspectives must be heard before closure |
| **Forgets prior decisions** | Conclusions land on Kanban (`task.result` of the motion); adopted conclusions become execution tasks automatically, and workers see the context through parent handoff |
| **Can't self-assess when stuck** | The chair's meta-decision loop: `continue \| dispatch \| vote \| close` — the framework asks the right question at the right time |
| **Hallucinates without evidence** | Dispatch mode sends a worker to investigate with real tools (`web_search`, `read_file`, `terminal`) before committing to an opinion |

### The chair role is different

Speakers do **domain reasoning** ("should we use SQLite or PostgreSQL?") — single-hop, structured input, within their expertise. The chair does **meta-reasoning** ("has everyone spoken? are there unresolved disagreements? is this ready to close?") — multi-hop, requires tracking global state.

**Recommendation:** if budget is constrained, use your strongest available model for the Leader/Chair and cheaper models for the other roles. The architecture's structural constraints — turn-taking, guided prompts, cross-validation — compensate for weaker speakers, but the chair's meta-cognitive load benefits from a more capable model.

---

## Tools (20)

**Project**

| Tool | Description |
|------|-------------|
| `agora_start_project` | Start a self-driving project |
| `agora_stop_project` | Stop a project (and clean up kanban) |
| `agora_project_status` | Check project status |
| `agora_update_project` | Change goal/stop_condition mid-flight (`reactivate=true` restarts a finished project) |

**Tasks**

| Tool | Description |
|------|-------------|
| `agora_create_task` | Create a kanban task |
| `agora_close_task` | Close/transition a task (`complete` / `cancel` / `submit_review`) |

**Discussion**

| Tool | Description |
|------|-------------|
| `agora_raise_motion` | Start a team discussion |
| `agora_get_messages` | Read discussion messages |
| `agora_get_result` | Get a closed discussion's conclusion |
| `agora_list_motions` | List active/closed discussions |
| `agora_close_motion` | Close a resolved or stale discussion |

**Team channel (new in 2.0)**

| Tool | Description |
|------|-------------|
| `agora_message` | Post to the team channel (`progress` / `blocking` / `mention`) |
| `agora_read_chat` | Read recent team-channel messages |

**Workers & teams**

| Tool | Description |
|------|-------------|
| `agora_create_worker` | Create a worker from a template |
| `agora_list_workers` | List all workers |
| `agora_remove_worker` | Remove a worker |
| `agora_list_templates` | List role templates |
| `agora_create_team` | Create a team |
| `agora_list_teams` | List teams |
| `agora_remove_team` | Remove a team |

> **`agora_close_task` actions:**
> - `complete` — mark the task done
> - `cancel` — archive the task
> - `submit_review` — transition to `review` status and auto-assign to the reviewer; the dispatcher auto-spawns them. After approval the task goes to `done`. Recommended when the team has a reviewer role.

## Kanban Hooks (3)

| Hook | When | Action |
|------|------|--------|
| `kanban_task_completed` | Worker finishes a task | Write the matching motion's conclusion as a task comment; if the task was complex (>1 run or >30 min), add a "consider saving this as a skill" nudge comment |
| `kanban_task_claimed` | Dispatcher assigns a task | Log the claim; inject the source motion's decision as a task comment |
| `kanban_task_blocked` | Worker blocks a task | If the reason mentions "design decision" or "motion", raise a discussion from that task automatically (the motion depends on the task, so context flows in) |

## AGENTS.md — Single Source of Truth

AGENTS.md is auto-generated in the project working directory. Hermes auto-injects it into every agent's system prompt (leader, discussion participants, kanban workers) via `TERMINAL_CWD` context file scanning.

**Contents:**
- Project name, goal, status, description
- Stop condition
- Team members table: `| Profile Name | Role (Template) |`
- Active discussions list
- Workflow instructions

**Refreshed on** (atomic write — temp file + `os.replace`): `start_project`, leader heartbeat, `agora_update_project`, motion create, motion close.

The heartbeat prompt itself is minimal — just a wake-up call. All context comes from AGENTS.md, with no prompt-level duplication.

## Architecture

```
agora/
├── plugin.yaml                  # Plugin manifest (20 tools + 3 hooks)
├── __init__.py                  # register(ctx)
├── tools/__init__.py            # 20 tool definitions + _wrap_handler
├── cli.py                       # hermes agora CLI
├── hooks/__init__.py            # 3 kanban hooks
├── project_planner.py           # Project lifecycle + heartbeat + AGENTS.md (atomic) + kanban cleanup on completion
├── agora/
│   ├── chat.py                  # Team-channel bus: chat root, [agora:msg] messages, cursor pull
│   ├── motion.py                # Motion = kanban sub-task: speech/votes/conclusion + discussion scheduler
│   ├── execution.py             # Discussion↔execution converter (motion→task / blocked→motion)
│   ├── kanban_compat.py         # Hermes module-split compatibility bridge (connect / notify, …)
│   ├── discussion/
│   │   ├── driver.py            # DiscussionDriver (speak/chair/vote/dispatch) + 429 retry (10x)
│   │   ├── agent_spawn.py       # Spawn Hermes agent subprocesses (3600s timeout)
│   │   ├── chair.py             # Chair prompts + speaker prompt builder
│   │   └── roles.py             # Discussion templates
│   ├── storage/
│   │   ├── motions_kanban.py    # Kanban-backed adapter for the 1.x motions API (2.0 hot path)
│   │   └── motions.py           # 1.x SQLite storage (kept for legacy consumers, off the 2.0 hot path)
│   ├── session_manager.py       # Session size tracking and rotation
│   ├── worker_templates.py      # 8 role templates (SOUL.md rendering, 2-channel self-growth)
│   ├── worker_manager.py        # Worker lifecycle (session locks, toolset writing, .env copy)
│   ├── team_manager.py          # Team and assignee routing
│   └── leader_loop.py           # Heartbeat + stuck-motion rescue + stale-state cleanup
├── dashboard/                   # Web UI + REST API
│   ├── plugin_api.py            # FastAPI routes
│   └── dist/                    # Compiled React frontend
└── skills/
    ├── agora-setup/             # Operator onboarding guide
    ├── agora-awareness/         # Framework knowledge (every worker should know this)
    └── agora-deliberation/      # Discussion methodology
```

### 2.0 data flow

```
                    ┌─────────────────────────┐
                    │   Leader (chair + arbiter)│
                    └────────────┬────────────┘
                                 │ heartbeat (15 min default)
                    ┌────────────▼────────────┐
                    │  Team channel = a persis-│
                    │  tent kanban task (in    │
                    │  'scheduled' state)      │
                    │  messages = [agora:msg]  │
                    │  motion = a sub-task     │
                    └────────────┬────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
        ┌─────▼─────┐      ┌─────▼─────┐      ┌─────▼─────┐
        │  worker   │      │  worker   │      │  worker   │
        │ private   │      │ private   │      │ private   │
        │ session   │      │ session   │      │ session   │
        └───────────┘      └───────────┘      └───────────┘

Discussion: inside the motion sub-task → speech / votes → conclusion into task.result
Execution:  adopted conclusion → tasks created automatically (parent = motion) → dispatcher runs them
Context:    injected by Hermes' native parent handoff — no leader transcription
```

## Timeout Configuration

All LLM-related timeouts default to **1 hour (3600s)**:

| Scenario | Default | Notes |
|----------|---------|-------|
| Speaker (`speak_timeout`) | 3600s | Worker spawned to take part in a discussion |
| Chair evaluation (`chair_timeout`) | 3600s | Leader evaluates the discussion state |
| Dispatch / investigation | 3840s | `speak_timeout + 240s` buffer |
| Voting | 3600s | Same as `speak_timeout` |

Hermes' HTTP client auto-retries on timeout; the Agora subprocess timeout is the hard ceiling — if exceeded, that worker is marked failed and the discussion continues.

## License

MIT

Full version history: [CHANGELOG.md](./CHANGELOG.md).
