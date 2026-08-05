---
name: agora-deliberation
description: Multi-role deliberation methodology — when to raise motions, how to participate in discussions, and how to act on discussion outcomes.
version: 0.1.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [agora, deliberation, discussion, consensus]
---

# Agora Deliberation — Discussion Methodology

## When to Raise a Motion

Raise a motion when you encounter a decision that benefits from multiple perspectives:

- **Design decisions** — "Should we use PostgreSQL or SQLite?" → architect + developer + reviewer
- **Technical trade-offs** — "JWT expiry: 1h vs 24h vs refresh token?" → architect + developer
- **Quality concerns** — "Should we standardize error handling?" → developer + reviewer
- **Architecture questions** — "Monolith vs microservices for this feature?" → architect + reviewer

Don't raise a motion for:
- Simple implementation choices (just do it)
- Questions with an obvious right answer
- Tasks already decided by the user

## How to Raise a Motion

```
agora_raise_motion(
    title="Short descriptive title",
    description="What's being discussed and why",
    context="task-abc123: found during implementation",
    blocking=True,  # if you need the answer before continuing
    participants=["architect", "developer"],  # optional: only needed roles
)
```

- `blocking=True` if you can't continue without the answer — your task pauses
- `blocking=False` if the discussion result is for future work — you continue

## Reading Discussion Results

After a discussion closes:

```
# Check the result
agora_get_result(motion_id="motion-xxx")

# Returns: decision (adopted/rejected), summary, action_items
```

Action items become kanban tasks automatically. Check your task list for new assignments.

## Discussion Flow

```
1. Motion raised → leader chairs event-driven discussion (no fixed round-robin)
2. Chair opens → states topic, picks first speaker + guidance question
3. Speaker speaks → real Hermes agent subprocess (SOUL.md, tools, session context)
4. Chair evaluates → continue? dispatch? vote? close? (JSON-based meta-decision)
5. Repeat 3-4 → until close or max_steps (default 30)
6. (Optional) Vote → each participant votes → chair decides outcome
7. Summary → chair generates action items + writes to MEMORY.md
8. Action items → kanban tasks (auto-dispatched to workers)
9. If blocking: source task unblocked with discussion result in comments
```

> **Speaker 429 retry (v1.8.8+):** If a worker hits API 429/rate-limit during discussion, `_speaker_speak` retries up to 10 times with incremental backoff (10s, 20s, …, 100s), clearing session on each retry. This prevents empty contributions from being stored as the worker's speech.
