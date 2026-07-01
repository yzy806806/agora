# Agora 🏛️

> Multi-role self-driving team plugin for [Hermes Agent](https://hermes-agent.nousresearch.com) — **v0.9.1**

[中文文档](./README_CN.md)

Agora turns Hermes into a self-driving team: multiple AI roles — each a **real Hermes agent subprocess** with its own SOUL.md, MEMORY.md, tools, and session context — discuss approaches, search the web, write content, and auto-dispatch tasks. The Leader acts as **chair** in event-driven discussions, dynamically picking speakers, evaluating progress, calling votes, and summarizing outcomes. Discussion results are written to each participant's MEMORY.md. The Leader plans the next phase, decides when the goal is achieved, and stops itself. Everything is managed from the Dashboard — no CLI needed.

## Key Features

| Feature | Description |
|---------|-------------|
| **Event-driven discussion engine** | Leader chairs discussions: opens topic, picks speakers dynamically, evaluates after each turn, calls votes, summarizes — no fixed round-robin |
| **Real agent subprocesses** | Each speaker is a real `hermes -p <profile> chat -q` spawn with SOUL.md, MEMORY.md, tools, and session context — not a stateless LLM call |
| **Session continuity** | Workers use `--resume` to maintain full conversation context across kanban tasks and discussions |
| **Memory persistence** | Discussion decisions and action items written to each participant's MEMORY.md for accumulated team knowledge |
| **8 role templates** | Architect, Developer, Reviewer, Tester, DevOps, Researcher, Writer, Leader |
| **Custom roles in discussions** | Custom (AI-generated) roles participate in discussions — identity comes from their SOUL.md, no pre-registration needed |
| **Leader = Planner + Chair** | Leader plans next phase, creates tasks, detects project completion, and chairs all team discussions |
| **Self-driving** | Heartbeat cron wakes Leader to check progress, unblock, plan |
| **Auto-stop** | Leader outputs PROJECT_COMPLETE when goal achieved, cron auto-paused |
| **Human participation** | Jump into discussions anytime via Dashboard input box |
| **Dashboard** | Projects/Team/Profiles tabs, event-driven discussion flow (steps, chair guidance, speaker turns, votes) |

## Install

```bash
hermes plugins install yzy806806/agora
hermes plugins enable agora
hermes gateway restart
```

## Quick Start

### 1. Create a team from Dashboard

Open `hermes dashboard`, go to the **Agora** tab:

1. **Team → Workers** — Pick a template or use AI to generate a custom role
2. **Team → Leaders** — Create a Leader, set heartbeat interval
3. **Team → Teams** — Select workers, form a team

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

**AI-generated roles:** Enter a name + one-line description (e.g. "Fashion editor, fact-checking and copyediting"), LLM generates a complete SOUL.md.

### 2. Start a project

In the **Projects** tab, click "Start Project":
- Name (e.g. `fashion-report`)
- Goal (e.g. "Write a 2026 spring/summer fashion trends PDF")
- Working directory
- Select team and leader
- Click create

### 3. Observe and participate

Click into a project to see:
- **Overview** — progress stats (todo/running/blocked/done)
- **Kanban** — real-time task board with assignees
- **Discussions** — event-driven discussion flow: chair guidance, speaker turns, votes, and summary + input box for human participation
- **Team** — member status (idle/working)

### 4. Leader self-driving

Each heartbeat, the Leader:
1. Checks blocked tasks → unblock/split/reassign
2. All done → plan next phase from goal, create tasks directly
3. Direction decision needed → raise motion for team discussion
4. Goal achieved → output `PROJECT_COMPLETE` → cron auto-paused

## Event-Driven Discussion Engine

The discussion engine was completely rewritten in v0.9.0. Instead of the old round-robin `ctx.llm.complete` approach, each discussion is now a **real meeting of real agents**:

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
| **Chair (Leader)** | Stateless meta-caller — evaluates discussion state, picks next speaker, calls votes. No `--resume` needed |
| **Role identity** | Comes from each worker's SOUL.md (including the **Discussion Protocol** section). Custom roles work automatically |
| **Leader SOUL.md** | Includes a **Chair Protocol** section: open, evaluate, redirect, vote, summarize |
| **Memory persistence** | Discussion decisions + action items written to each participant's MEMORY.md |
| **Config inheritance** | Worker profiles inherit root `config.yaml` (compression, approvals, etc.) |

### Human participation

The Dashboard discussion view shows the full event-driven flow: chair opening, speaker turns with guidance, vote calls, and final summary. A human can type into the discussion input box at any time — the message becomes part of the discussion history that the chair and speakers see.

## Dashboard Structure

| Tab | Content |
|-----|---------|
| **Projects** | Project list, start new project, project detail (kanban/discussions/team) |
| **Team** | Workers / Leaders / Teams management |
| **Profiles** | Profile config (model/SOUL.md/skills) |

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
├── plugin.yaml                  # Plugin manifest
├── __init__.py                  # register(ctx)
├── tools/__init__.py            # 18 tool definitions
├── cli.py                       # hermes agora CLI
├── hooks/__init__.py            # kanban_task_completed hook (memory + comment write-back)
├── project_planner.py           # Project lifecycle
├── agora/
│   ├── utils.py                 # Shared utilities
│   ├── discussion/              # Event-driven discussion engine (v0.9.0+)
│   │   ├── driver.py            #   DiscussionDriver: chair → speakers → evaluate → close
│   │   ├── agent_spawn.py       #   Spawn real Hermes agent subprocesses (hermes -p chat -q)
│   │   ├── chair.py             #   Chair (Leader) prompts: open, evaluate, vote, summary
│   │   └── roles.py             #   Consensus checker + discussion templates
│   ├── storage/                 # SQLite storage
│   ├── worker_templates.py      # 8 templates + AI soul generation (Discussion/Chair Protocol)
│   ├── worker_manager.py        # Worker lifecycle (profile inherits root config.yaml)
│   ├── team_manager.py          # Team + round-robin dispatch
│   ├── leader_manager.py        # Leader + auto cron
│   └── leader_loop.py           # Heartbeat + completion detection
├── dashboard/                   # Web UI + REST API (event-driven discussion flow)
└── skills/
```

## License

MIT
