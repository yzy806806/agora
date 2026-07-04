# Changelog

All notable changes to the Agora plugin are documented here.

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
