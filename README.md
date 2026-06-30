# Agora 🏛️

> Multi-role deliberation plugin for [Hermes Agent](https://hermes-agent.nousresearch.com)

Agora turns Hermes into a self-deliberating team. An LLM simulates multiple roles (architect, developer, reviewer, and more) discussing a topic, reaches consensus, and dispatches action items as kanban tasks — all within a single Hermes installation.

## Install

```bash
hermes plugins install yzy806806/agora
hermes plugins enable agora
hermes gateway restart
```

## Quick Start

### Start a discussion

```
/agora discuss Should we use PostgreSQL instead of SQLite?
```

Or via agent tool:

```python
agora_raise_motion(
    title="JWT expiry: 1h vs 24h vs refresh token?",
    description="Mobile users complain about frequent logouts",
    blocking=True,  # pause current task until discussion completes
)
```

### Use a discussion template

```python
agora_raise_motion(
    title="PostgreSQL vs MongoDB for analytics workload",
    template="tech_choice",  # pre-configures participants + focus areas
)
```

Available templates:
- `tech_choice` — technology selection with trade-off analysis
- `bug_analysis` — root cause investigation (includes tester role)
- `architecture_review` — design proposal evaluation
- `security_audit` — vulnerability assessment

### View discussions

```
/agora list                     — list all discussions
/agora show motion-abc123       — show discussion messages
/agora result motion-abc123     — show decision + action items
```

Or via CLI:

```bash
hermes agora list
hermes agora show motion-abc123
hermes agora result motion-abc123
hermes agora stats
```

### Dashboard

Open `hermes dashboard` and navigate to the **Agora** tab (after Kanban). From there you can:

- **Profiles** — create, configure, and manage agent profiles
  - One-click "Create Agora Team" creates architect + developer + reviewer profiles with preset SOUL.md
  - Edit each profile's model, provider, toolsets
  - Edit each profile's SOUL.md (personality/role definition)
  - View available skills per profile
- **Discussions** — browse past discussions, view messages and action items

## How It Works

```
/agora discuss "topic"
  │
  ▼
DiscussionDriver (ctx.llm)
  ├── Fetch source task context (if from kanban)
  ├── Round 1: architect → developer → reviewer
  ├── Consensus check (LLM, early stop if confidence ≥ 0.7)
  ├── Round 2: build on previous round
  ├── ... (max 3 rounds, or early consensus)
  │
  ▼
Summary (structured JSON via LLM)
  ├── decision: adopted / rejected / no_consensus
  ├── action_items: [{item, owner, depends_on}]
  ├── Per-role votes recorded (adopt/reject/abstain)
  │
  ▼
Kanban dispatch
  ├── Tasks created with parent-child dependencies
  ├── Result written back to source task
  ├── Decision written to MEMORY.md
  └── Kanban dispatcher auto-spawns workers
```

## Roles

### Built-in (default team)

| Role | Focus |
|------|-------|
| **Architect** | System design, tech stack, trade-offs |
| **Developer** | Implementation, feasibility, code structure |
| **Reviewer** | Quality, security, edge cases, testing |

### Extra roles (opt-in via config)

| Role | Focus |
|------|-------|
| **Tester** | Test strategy, coverage, automation |
| **DevOps** | CI/CD, deployment, infrastructure |
| **PM** | Requirements, priorities, timelines |

### Custom roles

Define your own roles in `~/.hermes/config.yaml`:

```yaml
plugins:
  entries:
    agora:
      agora:
        custom_roles:
          data_scientist: |
            You are a Data Scientist. Focus on data pipelines,
            model selection, and analytics infrastructure.
          sre: |
            You are an SRE. Focus on reliability, monitoring,
            and incident response.
```

Then include them in a discussion:

```python
agora_raise_motion(
    title="Design the data pipeline architecture",
    participants=["architect", "data_scientist", "devops"],
)
```

## Configuration

In `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - agora
  entries:
    agora:
      enabled: true
      llm:
        allow_model_override: true
        allow_profile_override: true
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
        custom_roles:
          # Add your own roles here
```

### Per-role model/profile

Each role can use a different model or even a different auth profile:

- `model:` — switch model within the current profile (requires `allow_model_override: true`)
- `profile:` — switch to a different Hermes profile entirely (requires `allow_profile_override: true`)

## Hermes Integration

Agora is deeply integrated with Hermes — no external services needed:

| Hermes Capability | Agora Usage |
|-------------------|-------------|
| `ctx.llm.complete()` | Drives multi-role discussion (async via `to_thread`) |
| `ctx.register_tool()` | 4 tools: raise_motion, get_messages, get_result, list_motions |
| `ctx.register_command()` | `/agora` slash command |
| `ctx.register_cli_command()` | `hermes agora` CLI |
| `ctx.register_hook()` | `kanban_task_completed` lifecycle hook |
| `kanban_db.create_task()` | Action items → kanban tasks with dependencies |
| `kanban_db.add_comment()` | Results written back to source tasks |
| `MemoryStore.add()` | Adopted decisions persisted to MEMORY.md |
| Dashboard plugin system | Profile management + discussion viewer tab |
| `profiles.create_profile()` | One-click team creation with presets |

### Lifecycle hooks

When a kanban task created by Agora completes, the `kanban_task_completed` hook:
1. Finds the originating motion
2. Writes the discussion result as a kanban comment
3. If the motion was adopted, writes a memory entry to `MEMORY.md`

### Background discussion safety

Non-blocking discussions run with:
- 5-minute timeout (marks motion as `no_consensus` on timeout)
- Error callback (logs and marks motion on failure)
- Task naming for debugging (`agora-discussion-{motion_id}`)

## Architecture

```
agora/
├── plugin.yaml              # plugin manifest (tools + hooks)
├── __init__.py              # register(ctx) — tools, commands, CLI, hooks
├── hooks/__init__.py        # kanban_task_completed lifecycle hook
├── tools/__init__.py        # 4 tools + /agora command + background runner
├── cli.py                   # `hermes agora` CLI subcommand
├── agora/
│   ├── discussion/
│   │   ├── driver.py        # LLM-driven discussion engine
│   │   └── roles.py         # role prompts + templates + presets
│   └── storage/
│       └── motions.py       # SQLite storage (motions + messages + votes)
├── dashboard/
│   ├── manifest.json        # dashboard tab declaration
│   ├── plugin_api.py        # 13 REST API endpoints
│   └── dist/
│       ├── index.js         # React frontend (via Plugin SDK)
│       └── style.css
└── skills/
    └── agora-deliberation/SKILL.md
```

## License

MIT
