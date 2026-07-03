# Agora 🏛️

> Multi-role self-driving team plugin for [Hermes Agent](https://hermes-agent.nousresearch.com) — **v1.0.0**

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
```

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
