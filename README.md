# Agora 🏛️

> Multi-role deliberation plugin for Hermes Agent

Agora turns Hermes into a self-deliberating team. The LLM simulates
architect/developer/reviewer roles discussing a topic, reaches consensus,
and dispatches action items as kanban tasks — all within a single Hermes
installation.

## Install

```bash
hermes plugins install yzy806806/agora
```

## Usage

### Start a discussion

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

### View discussions

```
/agora list                    — list all discussions
/agora show motion-abc123      — show discussion messages
/agora result motion-abc123    — show decision + action items
```

Or via CLI:

```bash
hermes agora list
hermes agora show motion-abc123
hermes agora result motion-abc123
```

## How It Works

```
/agora discuss "topic"
  │
  ▼
DiscussionDriver (ctx.llm)
  ├── Round 1: architect → developer → reviewer
  ├── Consensus check (LLM)
  ├── Round 2: build on previous round
  ├── ... (max 3 rounds, or early consensus)
  │
  ▼
Summary (structured JSON via LLM)
  ├── decision: adopted / rejected / no_consensus
  ├── action_items: [{item, owner}]
  │
  ▼
kanban_db.create_task()
  ├── task assigned to owner profile
  └── kanban dispatcher auto-spawns worker
```

- **No MCP server** — plugin uses `ctx.llm` directly
- **No external agents** — LLM simulates all roles
- **No Matrix/Telegram** — kanban dispatcher handles task dispatch
- **Agent can raise motions** — workers call `agora_raise_motion()` during tasks

## Configuration

In `~/.hermes/config.yaml`:

```yaml
plugins:
  entries:
    agora:
      enabled: true
      llm:
        allow_model_override: true
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

## Architecture

```
agora/
├── plugin.yaml          # plugin manifest (tools + hooks)
├── __init__.py          # register(ctx) — tools, commands, CLI, hooks
├── hooks/__init__.py    # kanban_task_completed lifecycle hook
├── tools/__init__.py    # 4 MCP tools + /agora slash command
├── cli.py               # `hermes agora` CLI subcommand
├── agora/
│   ├── discussion/
│   │   ├── driver.py    # LLM-driven multi-round discussion engine
│   │   └── roles.py     # role system prompts + summarizer
│   └── storage/
│       └── motions.py   # SQLite storage (motions + messages + votes)
└── skills/
    └── agora-deliberation/SKILL.md
```

- **No MCP server** — plugin uses `ctx.llm` directly
- **No external agents** — LLM simulates all roles
- **No Matrix/Telegram** — kanban dispatcher handles task dispatch
- **Agent can raise motions** — workers call `agora_raise_motion()` during tasks
- **Memory integration** — adopted decisions written to MEMORY.md
- **Kanban hooks** — task completion triggers result writeback

## License

MIT
