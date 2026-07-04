# Changelog

All notable changes to the Agora plugin are documented here.

## [1.2.1] — 2026-07-05

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
