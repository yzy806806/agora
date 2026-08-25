# Changelog

All notable changes to the Agora plugin are documented here.

## [1.9.0] — 2026-08-14

### Remove all residual memory writes (code review cleanup)

Full OCR audit found that despite v1.8.7 removing the *memory tool* and
*Self-Growth channel*, the code still **wrote** to MEMORY.md:

- `driver.py:_write_participant_memories` wrote discussion results to every
  participant + chair's MEMORY.md after each motion finalized — **deleted entirely** (3052 chars)
- `hooks/__init__.py:_write_to_memory` imported `MemoryStore` and wrote motion
  decisions to leader's MEMORY.md — **deleted entirely** + the hook call site
  that triggered it
- `driver.py` docstrings still said "Memory persistence: results written to
  each participant's MEMORY.md" — **fixed**
- `worker_templates.py` module docstring still said "recording memory" and
  "their memory persist across projects" — **fixed**

### Voting now has 429 retry protection

`_run_voting` and `_run_forced_vote` spawned agents directly via
`spawn_agent_speak` without 429 detection — API rate limits during voting
caused silent `abstain` fallbacks. Both now use the new `_spawn_with_retry`
method with 10 retries + incremental backoff (same as `_speaker_speak`).

### Stale docstrings fixed

- `driver.py` module docstring: removed `--resume` reference (disabled),
  changed "Memory persistence" to "Results stored in motions DB"
- `_speaker_speak` docstring: "3 times" → "10 times" (match actual max_retries)

### Files changed
- `agora/discussion/driver.py` — deleted `_write_participant_memories`,
  added `_spawn_with_retry`, fixed docstrings, voting uses retry
- `hooks/__init__.py` — deleted `_write_to_memory`, removed MemoryStore import
- `agora/worker_templates.py` — fixed module/docstring memory references
- `__init__.py` / `plugin.yaml` — version bump to 1.9.0

## [1.8.9] — 2026-08-13

### Native kanban review loop (request_review + request_changes)

Hermes v0.20.1 has first-class kanban review: `request_review`,
`request_changes`, `reopen_review_task` with worker-ownership checks and
reviewer provenance. Our hand-rolled `agora_close_task(action='submit_review')`
was a simplified version without the full loop.

**New review flow:**
```
developer → kanban_request_review(task_id, summary=...)
  → task moves to review, dispatcher auto-spawns reviewer
    → reviewer approves → kanban_complete → done
    → reviewer requests changes → kanban_request_changes(reason=...)
      → task auto-routes back to original implementer
      → developer fixes, re-submits via kanban_request_review
```

**Key benefits:**
- Worker ownership checks — can't submit someone else's task
- Reviewer provenance — implementer/reviewer recorded, auto-routing on rework
- Full closed loop — no leader intervention needed
- Removed our `submit_review` action (67 lines less code)

**Changes:**
- developer SOUL.md: `kanban_request_review` + re-submit after changes
- reviewer SOUL.md: approve with `kanban_complete`, reject with `kanban_request_changes`
- leader SOUL.md: review↔rework bounce detection in Step 2
- AGENTS.md Workflow: developer + reviewer sections updated
- `agora_close_task`: removed `submit_review` action

### stop_project deletes kanban tasks

`agora_stop_project` now deletes all project tasks (same as `on_project_complete`).
Previously the two completion paths were inconsistent — PROJECT_COMPLETE cleaned
up but stop_project didn't, leaving old tasks that confused the leader on restart.

### Files changed
- `agora/worker_templates.py` — review loop in developer/reviewer/leader SOUL
- `tools/__init__.py` — removed submit_review, docs updated
- `project_planner.py` — stop_project task deletion + AGENTS.md workflow
- `__init__.py` / `plugin.yaml` — version bump

## [1.8.8] — 2026-08-04

### Speaker 429 retry: 10 attempts with backoff

**Problem:** When a worker hit API 429 (rate limit) during a discussion, the
error message "API call failed after 3 retries: HTTP 429: authorization
failed" was stored directly as the worker's speech — it looked like the worker
spoke, but actually said nothing. The discussion continued with empty
contributions, and the chair couldn't tell the difference.

**Fix:** `_speaker_speak` now detects 429/rate-limit/authorization-failed errors
and retries up to 10 times with 10s/20s/.../100s incremental backoff. Session
is cleared on each retry for a fresh start.

Previously the dispatch/investigator path had `MAX_CONSECUTIVE_FAILURES=3`
tracking, but the normal speaker path had zero error detection.

### Delete kanban tasks on project completion

`on_project_complete` now deletes all project tasks (from all tables: tasks,
task_events, task_comments, task_runs, task_links) instead of leaving 290+ done
tasks in the DB. On project restart with a new goal, the kanban is empty.

### Files changed
- `agora/discussion/driver.py` — `_speaker_speak` 429 detection + 10 retries
- `project_planner.py` — `on_project_complete` deletes all tasks
- `__init__.py` / `plugin.yaml` — version bump

## [1.8.7] — 2026-08-04

### Delete all kanban tasks on project completion

**Problem:** When a project completed, `on_project_complete` only stopped the
heartbeat and set `status=completed`. All 290+ tasks remained in the kanban DB.
When the project was reactivated with a new goal, the leader saw the old tasks
and tried `PROJECT_COMPLETE` immediately — it didn't realize the project had
been restarted with new goals.

**Fix:** `on_project_complete` now calls `delete_archived_task()` for every
task in the project, removing all rows from `tasks`, `task_events`,
`task_comments`, `task_runs`, and `task_links`. On restart, the kanban is
empty and the leader correctly sees that new work needs to be created.

### Worker toolsets: memory removed, patch is part of file toolset

- Worker Self-Growth: 3 channels → 2 (Skills + SOUL.md, no Memory)
- Leader toolset: removed `memory` (not needed — skills + SOUL.md suffice)
- Fixed `patch` toolset warning — `patch` is part of `file`, not standalone

### Files changed
- `project_planner.py` — `on_project_complete` deletes all project tasks
- `agora/worker_templates.py` — Self-Growth 2 channels, no memory
- `agora/leader_loop.py` — leader toolset without memory
- `__init__.py` / `plugin.yaml` — version bump

## [1.8.6] — 2026-07-30

### Worker toolsets now written to config.yaml from template

Previously the template's `toolsets` field was dead code — `config.yaml` was
copied from global root (`hermes-cli` = all tools). Now
`_patch_config_toolsets()` writes the template's toolsets into
`platform_toolsets.cli` during worker creation.

**Worker toolsets** (all 7 roles): `terminal, file, web, skills, todo, session_search`

Removed tools workers don't need: `browser`, `tts`, `vision`, `code_execution`,
`computer_use`, `cronjob`, `delegation`, `clarify`, `memory`.

**Leader template toolsets**: `file, web, skills, todo, session_search`
(overridden in `leader_loop.py` spawn to add `agora` — no `terminal`).

### Worker memory removed — keep only Skills + SOUL.md

Workers no longer use the `memory` tool. Cross-project memory is not useful
(different projects, different stacks), skills already capture reusable
knowledge with better structure, and memory entries were low quality
(task logs, not lessons). Self-Growth section: 3 channels → 2.

### AGENTS.md Kanban Summary includes review status

- Now shows `Review` count alongside Running/Ready/Blocked/Done
- Shows "In review" task list (tasks in `review` status from `submit_review`)
- Shows "Ready (queued)" task list (not just running/blocked)

### Leader SOUL.md Step 2: granular crash escalation

Replaced vague "crashed → reassign" with 5-level escalation:
1. Crashed 1-2 times → let dispatcher retry
2. Same task crashed >2 times by same worker → reassign or split
3. Running >3 heartbeats no progress → raise motion
4. Task stuck in review >2 heartbeats → check reviewer availability

### Leader SOUL.md Step 4/5: submit_review auto-routing

- Step 4: "Code review is automatic — developers submit via
  `agora_close_task(action='submit_review')`, dispatcher auto-spawns reviewer.
  You do NOT need to create separate review tasks."
- Step 5: simplified — check worker summary + review findings, no manual
  review task verification needed

### AGENTS.md Workflow section updated

- Developer: `agora_close_task(action='submit_review')` when team has reviewer
- Other roles: `kanban complete` as usual
- "Never use Python, terminal, or direct DB calls" warning added
- Recent Decisions now filters 0-step bypassed motions (only shows
  `step_count > 0` adopted motions as ✅)

### Files changed
- `agora/worker_manager.py` — `_patch_config_toolsets()` function
- `agora/worker_templates.py` — refined toolsets, memory removed, Step 2/4/5
- `agora/leader_loop.py` — leader toolset (removed `memory`, `patch`)
- `project_planner.py` — AGENTS.md review status, ready list, workflow
- `tools/__init__.py` — `submit_review` action in `agora_close_task`
- `__init__.py` / `plugin.yaml` — version bump

## [1.8.5] — 2026-07-29

### Leader overhaul: restricted toolset + SOUL.md rewrite

**Problem:** The leader had `--toolsets hermes-cli` which includes `terminal`,
`code_execution`, `browser`, and `write_file`. This allowed the leader to:
- Bypass `agora_raise_motion` tool by calling Python/DB directly via terminal
  (motions created with empty project/chair → invisible in WebUI, stuck forever)
- Run tests and read code (violating "NEVER run tests yourself")
- Modify project code (violating "NEVER modify project code")
- Close motions manually as adopted without team discussion

**Fix:** Changed leader spawn toolset to `file,patch,web,skills,todo,memory,session_search,agora`.
No terminal, no code_execution, no browser. The leader can only:
- Read files (`read_file`, `search_files`) for project context
- Edit its own SOUL.md and MEMORY.md (`patch` — constrained by SOUL.md)
- Create skills (`skill_manage` — uses its own write path, not `write_file`)
- Manage project via agora tools (`agora_raise_motion`, `agora_create_task`, etc.)

**SOUL.md rewrite:**
- Identity: removed "reading code, tests" from assess role
- Core Constraints: "may read project docs, NEVER write project code"
- Step 1: assess via agora tools + AGENTS.md, not git log/terminal
- Step 5: verify via worker summaries, not running tests
- Step 6: use `agora_close_motion` to push stale motions to vote
- Post-Heartbeat Skill Review (replaces Post-Task — leader doesn't execute tasks)
  with leader-specific skill examples: assessment patterns, task decomposition,
  motion timing heuristics, stuck task recovery, phase transition checklists
- Self-Growth: "record what you learned, not what you did"
- Self-Growth: `patch` only (not `patch or write_file`)

### Worker SOUL.md shared sections — 4 improvements

1. **Discussion Protocol:** fixed terminal contradiction
   - Old: "may use terminal" + "do NOT use terminal" (contradictory)
   - New: "terminal for read-only commands" + "do NOT use to change files"

2. **Post-Task Skill Review:** broadened for all roles
   - Old: "technique, fix, or workaround" (developer-centric)
   - New: "technique, pattern, or workflow" + per-role-type examples
     (test strategy, doc structure, research method, review checklist)

3. **Self-Growth:** patch only, no `write_file`
   - Old: "Use `patch` or `write_file` to edit SOUL.md"
   - New: "Use `patch`" + "only patch own SOUL.md and MEMORY.md"

4. **Self-Growth Memory:** "record what you learned, not what you did"

5. **Researcher:** removed duplicate Discussion Protocol section
   (`render_soul()` auto-appends the standard one)

### Storage-level adopted guard (from v1.8.4, detailed here)

`update_motion_status()` now rejects `decision="adopted"` on motions with
0 steps or 0 messages — automatically downgrades to `error`. This is the
storage-layer last line of defense against bypassing the discussion engine
via terminal/DB access. Tool-level guard in `agora_close_motion` only
protected the tool-call path.

### _rescue_stuck_motions scans empty-project motions

Motions created before v1.8.3 (project resolution fix) had `project=''`
and were invisible to `_rescue_stuck_motions` (which filtered by
`project=project_name`). Added raw SQL query to also find active motions
with empty/NULL project, dedup by motion id.

### AGENTS.md Team Members table includes responsibilities

The Team Members table now has a Responsibilities column so the leader
knows what each role does without reading their SOUL.md:
```
| Profile Name | Role | Responsibilities |
| tester | tester — Tester | Test strategy, automated tests, ... |
| reviewer | reviewer — Reviewer | Code review, security review, ... |
```

### Files changed
- `agora/leader_loop.py` — restricted toolset, NULL tenant query, rescue empty-project
- `agora/worker_templates.py` — all shared sections + researcher dedup
- `agora/storage/motions.py` — storage-level adopted guard
- `project_planner.py` — NULL tenant query, role responsibilities, team warning
- `tools/__init__.py` — always resolve project in agora_raise_motion
- `dashboard/plugin_api.py` — NULL tenant query in _count_tasks
- `__init__.py` / `plugin.yaml` — version bump

## [1.8.4] — 2026-07-29

### Fix: Storage-level guard prevents bypassing discussion engine

**Root cause:** The `agora_close_motion` tool had a guard that rejected
`adopted` on 0-step motions, but this only protected the tool-call path.
The leader agent (which has terminal access) could bypass it by calling
`update_motion_status()` directly via Python/terminal, closing a
never-discussed motion as `adopted`.

This happened in production: the leader raised a project-completion
motion, then on the next heartbeat manually closed it as `adopted`
without any discussion — skipping the team vote entirely.

**Fix:** Added the same `adopted` guard in `update_motion_status()`
(storage layer), which is the last line of defense. Any code path —
tool calls, CLI, direct DB access via terminal — is now checked.
If `adopted` is requested on a motion with 0 steps or 0 messages,
the decision is automatically downgraded to `error` with an
explanatory rationale.

### Fix: Leader SOUL.md enforces mandatory completion discussion

Added a "Project completion motion — MANDATORY DISCUSSION" section
to the leader template that explicitly forbids:
- Closing a completion motion with `agora_close_motion`
- Using terminal/DB commands to close motions
- Declaring `PROJECT_COMPLETE` without a real team vote

The leader must wait for the discussion driver to complete the vote
and check `agora_get_result()` before declaring completion.

Updated in both:
- `agora/worker_templates.py` (template for new leaders)
- `~/.hermes/profiles/leader/SOUL.md` (existing leader)

### Files changed
- `agora/storage/motions.py` — storage-level adopted guard
- `agora/worker_templates.py` — SOUL.md mandatory discussion section
- `__init__.py` / `plugin.yaml` — version bump

## [1.8.3] — 2026-07-28

### Fix: AGENTS.md and check_project_complete miss tasks with NULL tenant

Tasks created via kanban CLI (not `agora_create_task`) have
`tenant=NULL`. `list_tasks(tenant=board)` only matches non-NULL
tenants, so these tasks were invisible in:

- **AGENTS.md Kanban Summary** — leader saw empty kanban, created
  duplicate tasks or raised PROJECT_COMPLETE prematurely
- **`check_project_complete`** — pending task gate didn't count
  NULL-tenant tasks, allowing premature project completion
- **Dashboard task counts** — project view showed wrong numbers

Fixed all 3 locations to query `tenant = ? OR tenant IS NULL`:

- `project_planner.py: update_project_agents_md()`
- `agora/leader_loop.py: check_project_complete()`
- `dashboard/plugin_api.py: _count_tasks()`

### Fix: `agora_raise_motion` doesn't always set project field

Project auto-resolution only ran when participants or chair were
missing (`if not participants or not chair`). When the leader
provided participants but not the project, the motion was created
with `project=''`, making it invisible to `_rescue_stuck_motions`
(which filters by project) — the motion stuck at 0 steps forever.

Now project resolution always runs. Chair and participants are
still only auto-filled when not provided.

### Fix: `start_project` warns when called without a team

Without a team bound, task assignee routing falls back to the
`default` profile instead of the correct worker. Added a warning
log so the issue is visible in gateway logs.

### Files changed
- `project_planner.py` — NULL tenant query + team warning
- `agora/leader_loop.py` — NULL tenant query in check_project_complete
- `dashboard/plugin_api.py` — NULL tenant query in _count_tasks
- `tools/__init__.py` — always resolve project in agora_raise_motion
- `__init__.py` — version bump
- `plugin.yaml` — version bump

## [1.8.2] — 2026-07-28

### Fix: `patch_config_model` fails on flat `model:` format — workers get "No inference provider configured"

**Root cause:** `patch_config_model()` in `utils.py` used a regex that
only matched the new dict format (`model:\n  default: <name>`). When
`hermes config set model <name>` writes the old flat string format
(`model: <name>`), the regex silently fails to match, leaving the
config with a flat `model: glm5.2` string instead of
`model:\n  default: glm5.2`. Hermes cannot resolve the provider or
API key from a flat string, so workers fail with "No inference
provider configured".

The old code also swallowed all exceptions silently (`except: pass`),
making the failure invisible.

**Fix:** Rewrote `patch_config_model()` to handle three cases:
1. New dict format (`model:\n  default: <name>`) — update in place
2. Old flat format (`model: <name>`) — upgrade to dict format
3. No model field at all — insert at top of file

Added proper logging on all paths (success + failure).

Files changed:
- `agora/utils.py` — rewrote `patch_config_model()`
- `__init__.py` — version bump
- `plugin.yaml` — version bump

## [1.8.1] — 2026-07-28

### Critical: Worker profiles missing .env — "No inference provider configured"

**Root cause:** `create_worker()` in `worker_manager.py` linked global
plugins (step 1e) and injected external skills (step 1d) into each
worker profile, but did not link the global `~/.hermes/.env` file.

Workers spawned with `-p <profile>` have `HERMES_HOME` pointing at
their profile directory (`~/.hermes/profiles/<name>/`). Hermes reads
`<profile>/.env` for API keys and secrets. Without the link, workers
cannot find credentials and fail with:

> No inference provider configured. Run 'hermes model' to choose a
> provider and model, or set an API key (OPENROUTER_API_KEY,
> OPENAI_API_KEY, etc.) in ~/.hermes/.env.

This caused every leader heartbeat to fail silently — the leader
agent spawned, immediately hit the error, and produced no tasks,
motions, or output.

**Fix:** Added `_link_global_env()` function (mirrors the existing
`_link_global_plugins` pattern) and call it as step 1f in
`create_worker()`. Symlinks the global `.env` into the profile
directory, respecting existing files/symlinks (manual overrides).

Files changed:
- `agora/worker_manager.py` — new `_link_global_env()` + step 1f call
- `__init__.py` — version bump
- `plugin.yaml` — version bump

## [1.3.0] — 2026-07-05

### Discussion engine — critical fixes

- **Leader couldn't call Agora tools**: `leader_loop.py` spawned the leader
  without `--toolsets agora`, so the leader had no access to
  `agora_raise_motion`, `agora_list_motions`, etc. This meant the leader
  couldn't initiate discussions or votes — it single-handedly decided
  project completion without team input. Now passes `--toolsets agora`.
- **Discussion participants had no Agora tools**: `agent_spawn.py` spawned
  worker agents for discussion without `--toolsets agora`, causing
  `Warning: Unknown toolsets: messaging` errors and failed investigations.
  Now passes `--toolsets agora`.
- **Motions stuck at "discussing" round 0**: `kanban_task_blocked` hook
  created motions without resolving chair/participants, so
  `spawn_discussion_driver` never fired. The hook now auto-resolves
  chair and participants from the project and spawns the driver.
- **No recovery for stuck motions**: Added `_rescue_stuck_motions()` to
  `leader_loop.py` — runs before each heartbeat spawn, finds motions stuck
  in "discussing" with 0 messages, re-resolves chair/participants, and
  re-spawns the discussion driver. Also closes empty-title motions.

## [1.2.2] — 2026-07-05

### Dashboard fixes

- **Kanban tasks not showing in Agora tab**: frontend was calling
  non-existent `/api/kanban/tasks?project=` endpoint. Added
  `/projects/{name}/tasks` API that queries the kanban DB directly.
- **Task counts always 0**: `list_projects` and `get_project` API
  now populate `task_counts` (todo/running/blocked/done) from the
  kanban DB.
- **Heartbeat always shows "Currently paused"**: `get_cron_status`
  was hardcoded to read `~/.hermes/profiles/coder/cron/jobs.json`
  which doesn't exist. Now reads `~/.hermes/cron/jobs.json` (default
  profile).

### Dead code cleanup

- Removed `profile` parameter from `start_project()` — it was written
  to `project.json` but never read back by any code. Worker profiles
  are determined by worker name (set at creation time), not by this
  field.
- Removed `source_profile` from `create_motion()` — written to DB
  but never read for any logic. DB column retained for compatibility.
- Removed hardcoded `profiles/coder/` path from heartbeat script.
- Removed `_get_active_profile()` helper (no longer referenced).

## [1.1.0] — 2026-07-04

### Discussion engine: infinite loop fix

**Root cause:** A motion with an empty title (`title=""`) would enter the
discussion loop but never terminate — the chair kept dispatching the
developer to investigate, the dispatch failed (no workdir → worker can't
find project files), and the loop had no failure limit, spawning worker
processes indefinitely.

Three fixes:

1. **Empty-title abort** (`driver.py`): motions with `title=""` or
   `title="   "` are now aborted immediately with `decision="error"`
   before entering the discussion loop.

2. **Dispatch failure limit** (`driver.py`): added a
   `consecutive_failures` counter. When an investigator's dispatch fails
   (empty reply or error placeholder) 3 times in a row, the loop breaks
   and forces a vote instead of retrying endlessly.

3. **Workdir fallback** (`tools/__init__.py`): when `source_task_id` is
   `None` (leader raised the motion outside a kanban task), the workdir
   was never resolved — it stayed as `""`, so dispatched workers ran in
   `/root` instead of the project directory. Now falls back to
   `resolved_project` (the project name already resolved during motion
   creation) to look up the workdir from the project registry.

## [1.0.0] — 2026-07-04

### Critical: Worker process `No module named 'agora'` fix

Worker processes (leader, developer, architect, etc.) dispatch tool
handlers in their own Python process, where the Agora plugin root
directory is **not** on `sys.path`. This caused every Agora tool call
from workers to fail with `ModuleNotFoundError: No module named 'agora'`
— `agora_project_status`, `agora_list_workers`, `agora_start_project`,
etc. were all broken in worker context.

The dashboard's `plugin_api.py` already had a `sys.path.insert()` fix
for this; `tools/__init__.py` was missing the same fix.

**Fix:** Added plugin-root `sys.path` insertion at the top of
`tools/__init__.py`, mirroring the pattern already in
`dashboard/plugin_api.py`.

### Project creation: Description & Stop Condition

`start_project` now accepts `description` and `stop_condition`
parameters. Both are written to the project's `AGENTS.md` so workers
can see the full project context and know when the project should
stop. The stop condition is informational — workers can reference it
when deciding whether to raise a motion suggesting project completion.

**Stop button = force stop, no voting.** The dashboard Stop button
directly stops the project (pauses heartbeat, marks status as
`stopped`). No voting mechanism.

### Project management fixes

**Auto-create workdir:** `start_project` now creates the workdir
directory if it doesn't exist.

**Separate Stop and Delete:**
- `POST /projects/{name}/stop` — pauses heartbeat, marks project stopped
- `DELETE /projects/{name}` — permanently deletes (removes cron,
  unbinds workers, deletes registry file)
- Frontend: active projects show **Stop**; stopped projects show
  **Delete**

### Worker creation fixes

**clone_from defaults to None:** All three entry points (tool schema,
dashboard API, deprecated leader_manager) defaulted `clone_from` to
`"coder"`, causing a 400 error when no `coder` profile exists. Default
is now `None`.

**Lowercase worker names:** Dashboard passed display names (e.g.
`"Architect"`) as profile names, creating uppercase directories that
`hermes profile list` couldn't see. `create_worker` now normalises to
lowercase.

### Worker self-evolution: profile isolation

**HERMES_HOME override removed:** All Agora spawn points overwrote
`HERMES_HOME` to the global root, destroying profile isolation. Workers
shared one MEMORY.md, one skills pool, one sessions DB. Removed the
override in `leader_loop.py` so `-p` flag works correctly.

**Shared skills access:** `create_worker` injects
`skills.external_dirs` into worker's `config.yaml`, pointing at the
global skills directory. Workers can read 40+ shared skills while
keeping their own `skills/` for personal skills.

**SOUL.md self-growth guidance:** All SOUL.md templates include a
`## Self-Growth` section with exact filesystem paths for the three
self-evolution channels (Memory, Skills, SOUL.md).

### Dashboard skills API fix

The `/profiles/{name}/skills` endpoint only scanned the profile-local
`skills/` directory. It now scans both local and `external_dirs`
directories, filters out `skills.disabled`, and reports each skill's
source.

### Files changed
- `tools/__init__.py` — sys.path fix for worker process; clone_from
  schema default removed
- `project_planner.py` — `start_project` auto-creates workdir, accepts
  description/stop_condition; `stop_project` force stop
- `dashboard/plugin_api.py` — split stop/delete APIs; fix skills
  endpoint; StartProjectRequest adds description/stop_condition
- `dashboard/dist/index.js` — Stop/Delete buttons; description/stop
  condition form fields
- `agora/leader_loop.py` — removed HERMES_HOME override
- `agora/worker_manager.py` — lowercase names;
  `_inject_external_skills()`
- `agora/worker_templates.py` — `_SELF_GROWTH_SECTION` in SOUL.md
- `agora/leader_manager.py` — clone_from default None
