# Agora 🏛️

> Multi-role self-driving development plugin for [Hermes Agent](https://hermes-agent.nousresearch.com)

[中文文档](./README_CN.md)

Agora transforms Hermes into a self-driving development team: multiple AI roles discuss approaches, reach consensus, generate tasks, dispatch them to workers, and auto-review — all within a single Hermes instance.

## Key Features

| Feature | Description |
|---------|-------------|
| **Multi-role deliberation** | LLM-driven architect/developer/reviewer debate with automatic consensus |
| **Auto task dispatch** | Discussion outcomes become kanban tasks with dependencies |
| **Worker management** | 6 role templates, create independent profiles from Dashboard |
| **Team composition** | Group workers into teams, round-robin task assignment, cross-project reuse |
| **Leader heartbeat** | Periodic Leader wake-up to check project health, unblock/split/plan |
| **Dashboard UI** | Web interface for worker/leader/team management and discussion browsing |

## Install

```bash
hermes plugins install yzy806806/agora
hermes plugins enable agora
hermes gateway restart
```

## Quick Start

### 1. Create a team from Dashboard

Open `hermes dashboard`, go to the **Agora** tab:

1. **Team → Workers** — Pick a template (e.g. Developer 💻) → Name it (e.g. `backend-dev`) → Create
2. **Team → Leaders** — Name, select project, set heartbeat interval (e.g. 15 min) → Create
3. **Team → Teams** — Select workers, bind to project

Each worker auto-generates:
- `SOUL.md` — Role identity (behavior rules, responsibility boundaries)
- `MEMORY.md` — Personal memory (accumulates experience across projects)
- `config.yaml` — Cloned from parent profile (API keys, model, etc.)
- `skills/` — Independent skills directory

### 2. Start a discussion

```
/agora discuss Should we use PostgreSQL instead of SQLite?
```

Or via agent tool:
```python
agora_raise_motion(
    title="JWT expiry: 1h vs 24h vs refresh token?",
    description="Mobile users complain about frequent logouts",
    blocking=True,
)
```

### 3. Self-driving project

```python
agora_start_project(
    name="my-app",
    goal="Build a REST API service",
    workdir="/root/my-app",
    team="my-team",
    max_rounds=10,
)
```

The Leader auto-wakes every 15 minutes to:
1. Check blocked tasks → unblock/split/reassign
2. Check triaged tasks → analyze failures
3. All done → plan next phase
4. Check stale motions → close and decide

## Role Templates

| Template | Icon | Responsibilities |
|----------|------|-----------------|
| Architect | 🏗️ | System design, API contracts, tech selection |
| Developer | 💻 | Feature implementation, testing, dependency management |
| Reviewer | 🔍 | Code review, security, edge cases |
| Tester | 🧪 | Test strategy, automation, bug reporting |
| DevOps | 🚀 | CI/CD, containerization, deployment, monitoring |
| Team Leader | 👨‍💼 | Project monitoring, unblocking, phase planning |

**Profile = a person**: config/memory/skills/persona are reusable across projects; kanban tasks/motions/workdir are project-isolated.

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
          auto_create_tasks: true
        roles:
          architect:
            model: deepseekv4pro
          developer:
            model: astron-code-latest
          reviewer:
            model: kimi2.6
```

## Tools

18 tools registered with Hermes:

- **Discussion**: `agora_raise_motion`, `agora_get_messages`, `agora_get_result`, `agora_list_motions`
- **Project**: `agora_start_project`, `agora_stop_project`, `agora_project_status`
- **Workers**: `agora_create_worker`, `agora_list_workers`, `agora_remove_worker`, `agora_list_templates`
- **Teams**: `agora_create_team`, `agora_list_teams`, `agora_remove_team`
- **Leaders**: `agora_create_leader`, `agora_list_leaders`, `agora_remove_leader`, `agora_leader_heartbeat`

## Architecture

```
agora/
├── plugin.yaml                  # Plugin manifest (18 tools + 1 hook)
├── __init__.py                  # register(ctx)
├── tools/__init__.py            # 18 tool definitions
├── cli.py                       # hermes agora CLI
├── hooks/__init__.py            # kanban_task_completed hook
├── project_planner.py           # Self-driving engine
├── agora/
│   ├── discussion/              # LLM discussion engine
│   ├── storage/                 # SQLite (motions + messages)
│   ├── worker_templates.py      # 6 role templates (SOUL.md)
│   ├── worker_manager.py        # Worker lifecycle
│   ├── team_manager.py          # Team + round-robin dispatch
│   ├── leader_manager.py        # Leader + auto cron
│   └── leader_loop.py           # Heartbeat trigger
├── dashboard/                   # Web UI + REST API
└── skills/
```

## License

MIT
