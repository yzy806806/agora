---
name: agora-setup
description: Set up an Agora multi-agent team from scratch — create workers, form teams, start projects. Read this when the user wants to use Agora for collaborative development.
category: collaboration
version: 1.0.0
---

# Agora Setup — From Zero to Running Team

Use this skill when the user wants to set up an Agora multi-agent team for
collaborative software development. This covers the full setup flow: creating
workers, forming a team, and starting a self-driving project.

## Prerequisites

- Hermes Agent installed and running
- Agora plugin enabled (`hermes plugins enable agora` + restart gateway)

## Quick Start (3 Steps)

### Step 1: Create Workers

Create workers from role templates. Each worker is a Hermes profile with its
own SOUL.md (identity), MEMORY.md, and skills directory.

```
# List available templates
agora_list_templates()

# Create a leader (required — chairs discussions, runs heartbeat)
agora_create_worker(name="leader", role="leader")

# Create team members (pick roles relevant to your project)
agora_create_worker(name="developer", role="developer")
agora_create_worker(name="architect", role="architect")
agora_create_worker(name="tester", role="tester")
```

**Available templates:**

| Role | Best For |
|------|----------|
| `leader` | Project management, discussion chair, heartbeat (required) |
| `architect` | System design, API contracts, tech selection |
| `developer` | Implementation, testing, dependencies |
| `reviewer` | Code review, security, edge cases |
| `tester` | Test strategy, automation, bug reporting |
| `devops` | CI/CD, deployment, infrastructure |
| `researcher` | Web research, trend analysis, information synthesis |
| `writer` | Documentation, content, README |

**Tips:**
- Worker names become Hermes profile names. Use simple lowercase names.
- You need at least a `leader` + 2 workers for meaningful discussions.
- Workers persist across projects — create them once, reuse forever.
- Workers can be assigned any model via Dashboard → Profiles → Config.

### Step 2: Form a Team

```
agora_create_team(
    team_name="alpha",
    workers=["leader", "architect", "developer", "tester"],
)
```

A team is the assignee pool for a project. The same worker can be on
multiple teams.

### Step 3: Start a Project

```
agora_start_project(
    name="my-project",
    workdir="/path/to/project/repo",
    goal="Build a REST API with authentication and pagination",
    stop_condition="All endpoints tested and documented",
    heartbeat_member="leader",   # who wakes on heartbeat
    heartbeat_minutes=30,        # heartbeat interval
)
```

That's it. The leader will wake up on the next heartbeat, read AGENTS.md
for project context, and start working autonomously.

## What Happens Next

1. **Heartbeat fires** → leader wakes, reads AGENTS.md, checks kanban
2. **Leader plans** → creates tasks, assigns to workers via kanban
3. **Workers execute** → dispatcher spawns workers for each task
4. **Discussions** → leader raises motions for design decisions, workers debate
5. **Self-stop** → when stop condition is met, leader raises a motion to vote

## Monitoring

```
# Check project status
agora_project_status(name="my-project")

# List active discussions
agora_list_motions(status="active")

# Get discussion result
agora_get_result(motion_id="motion-xxx")

# Read discussion messages
agora_get_messages(motion_id="motion-xxx")
```

Or open the Dashboard: `hermes dashboard` → Agora tab.

## Updating Projects Mid-Flight

Change direction without stopping:

```
agora_update_project(
    name="my-project",
    goal="Pivot to GraphQL API",
    stop_condition="GraphQL schema complete and tested",
)
```

All workers see the new goal on their next spawn (via AGENTS.md).

To restart a completed project:

```
agora_update_project(
    name="my-project",
    goal="Add multi-tenant support",
    reactivate=True,
)
```

## How Worker Assignment Works

- Tasks are assigned by **role name** (e.g. `assignee="developer"`), not by
  worker name. The system routes to the correct worker automatically.
- The leader decides which role to assign based on the discussion outcome.
- Workers see the team roster (name → role) in AGENTS.md.

## Discussion Templates

For common decision types, use a template:

```
agora_raise_motion(
    title="Should we use SQLite or PostgreSQL?",
    template="tech_choice",
)
```

| Template | Participants | Use When |
|----------|-------------|----------|
| `tech_choice` | architect, developer, reviewer | Choosing between technologies |
| `bug_analysis` | developer, tester, reviewer | Root cause analysis |
| `architecture_review` | architect, developer, reviewer | Design review |
| `security_audit` | reviewer, developer, architect | Security assessment |

## Common Patterns

### Minimal Team (3 members)
- `leader` — manages project, chairs discussions
- `developer` — writes code
- `tester` — tests and validates

### Full Development Team (6 members)
- `leader` — management
- `architect` — design
- `developer` — implementation
- `reviewer` — code review
- `tester` — QA
- `researcher` — research and analysis

### Content Creation Team (4 members)
- `leader` — editorial direction
- `researcher` — fact-finding
- `writer` — content production
- `reviewer` — editorial review

## Troubleshooting

- **Workers not picking up tasks?** Check that the gateway is running and
  the kanban dispatcher is active: `hermes gateway status`
- **Discussions not starting?** Check that the leader has `--toolsets agora`
  (it should be automatic). Check `agora_list_motions(status="active")`.
- **Heartbeat not firing?** Check cron: `hermes cron list`. Look for
  `heartbeat-<project_name>`.
- **Worker memory full?** Workers have a 2200-char memory limit. Use
  `agora_remove_worker` + `agora_create_worker` to reset, or edit
  `~/.hermes/profiles/<name>/memories/MEMORY.md` manually.
