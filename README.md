# Agora 🏛️

> Multi-role self-driving team plugin for [Hermes Agent](https://hermes-agent.nousresearch.com)

[中文文档](./README_CN.md)

Agora turns Hermes into a self-driving team: multiple AI roles discuss approaches, search the web, write content, and auto-dispatch tasks. The Leader plans the next phase, decides when the goal is achieved, and stops itself. Everything is managed from the Dashboard — no CLI needed.

## Key Features

| Feature | Description |
|---------|-------------|
| **8 role templates** | Architect, Developer, Reviewer, Tester, DevOps, Researcher, Writer, Leader |
| **AI-generated roles** | Describe a role in natural language, LLM generates SOUL.md |
| **Leader = Planner** | Leader plans next phase, creates tasks, detects project completion |
| **Self-driving** | Heartbeat cron wakes Leader to check progress, unblock, plan |
| **Auto-stop** | Leader outputs PROJECT_COMPLETE when goal achieved, cron auto-paused |
| **Human participation** | Jump into discussions anytime via Dashboard input box |
| **Dashboard** | Projects/Team/Profiles tabs, full web-based workflow |

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
- **Discussions** — live discussion feed + input box for human participation
- **Team** — member status (idle/working)

### 4. Leader self-driving

Each heartbeat, the Leader:
1. Checks blocked tasks → unblock/split/reassign
2. All done → plan next phase from goal, create tasks directly
3. Direction decision needed → raise motion for team discussion
4. Goal achieved → output `PROJECT_COMPLETE` → cron auto-paused

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
```

## Architecture

```
agora/
├── plugin.yaml                  # Plugin manifest
├── __init__.py                  # register(ctx)
├── tools/__init__.py            # 18 tool definitions
├── cli.py                       # hermes agora CLI
├── hooks/__init__.py            # kanban_task_completed hook
├── project_planner.py           # Project lifecycle
├── agora/
│   ├── utils.py                 # Shared utilities
│   ├── discussion/              # LLM discussion engine
│   ├── storage/                 # SQLite storage
│   ├── worker_templates.py      # 8 templates + AI soul generation
│   ├── worker_manager.py        # Worker lifecycle
│   ├── team_manager.py          # Team + round-robin dispatch
│   ├── leader_manager.py        # Leader + auto cron
│   └── leader_loop.py           # Heartbeat + completion detection
├── dashboard/                   # Web UI + REST API
└── skills/
```

## License

MIT
