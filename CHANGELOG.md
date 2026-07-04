# Changelog

All notable changes to the Agora plugin are documented here.

## [1.2.0] — 2026-07-04

### Project management fixes

**Auto-create workdir:** `start_project` now creates the workdir directory
if it doesn't exist. Previously, specifying a non-existent path caused the
project to fail silently on heartbeat.

**Separate Stop and Delete:** The dashboard previously had a single "Stop"
button that only marked a project as `stopped` — there was no way to
permanently delete a project. Now:
- `POST /projects/{name}/stop` — pauses heartbeat, marks project as stopped
- `DELETE /projects/{name}` — permanently deletes (removes cron, unbinds
  workers, deletes registry file)
- Frontend: active projects show **Stop** button; stopped projects show
  **Delete** button

### Worker creation fixes

**clone_from defaults to None:** All three entry points (tool schema,
dashboard API, deprecated leader_manager) defaulted `clone_from` to
`"coder"`, causing a 400 error when no `coder` profile exists. The default
is now `None` — workers copy the global `config.yaml` directly.

**Lowercase worker names:** The dashboard passed display names (e.g.
`"Architect"`) as profile names, creating directories with uppercase
letters that `hermes profile list` couldn't see. `create_worker` now
normalises names to lowercase.

### Dashboard skills API fix

The `/profiles/{name}/skills` endpoint only scanned the profile-local
`skills/` directory, ignoring `external_dirs` and `disabled` config. It now:
- Scans both local and `external_dirs` directories
- Filters out skills listed in `skills.disabled`
- Reports each skill's source (`local` or `external`)

### Files changed
- `project_planner.py` — `start_project` auto-creates workdir; new `delete_project()`
- `dashboard/plugin_api.py` — split stop/delete APIs; fix skills endpoint
- `dashboard/dist/index.js` — Stop/Delete button logic
- `agora/worker_manager.py` — lowercase name normalisation
- `agora/leader_manager.py` — `clone_from` default None
- `tools/__init__.py` — `clone_from` schema default removed

## [1.1.0] — 2026-07-04

### Worker self-evolution: profile isolation fix

**Root cause:** All Agora spawn points overwrote `HERMES_HOME` back to the
global root (`~/.hermes/`), destroying the profile isolation that
`hermes -p <profile>` provides. This meant every worker shared:
- One `MEMORY.md` file (all roles' experience mixed together)
- One `skills/` pool (worker-created skills polluted the global pool)
- One sessions DB (no per-worker conversation isolation)

**Fix:** Removed the `HERMES_HOME` override in `leader_loop.py`. The `-p`
flag now correctly sets `HERMES_HOME` to `~/.hermes/profiles/<name>/`,
giving each worker isolated memory, skills, and sessions.

### Worker self-evolution: shared skills access

New workers' profile-local `skills/` directory is nearly empty. Without
access to the global `~/.hermes/skills/` directory, workers would be
blind to the 40+ shared skills (github, debugging, plan, agora-awareness,
etc.).

**Fix:** `create_worker` now injects `skills.external_dirs` into the
worker's `config.yaml`, pointing at the global skills directory. Workers
can read all shared skills while keeping their own `skills/` dir for
personal skills they create via `skill_manage`.

### Worker self-evolution: SOUL.md self-growth guidance

All SOUL.md templates now include a `## Self-Growth` section with exact
filesystem paths for the three self-evolution channels:
1. **Memory** — `~/.hermes/profiles/<name>/memories/MEMORY.md`
2. **Skills** — `~/.hermes/profiles/<name>/skills/` (personal) + `~/.hermes/skills/` (shared)
3. **SOUL.md** — `~/.hermes/profiles/<name>/SOUL.md`

Workers can now edit their own SOUL.md, record memory, and create skills
without guessing paths.

### Files changed
- `agora/leader_loop.py` — removed `HERMES_HOME` override in spawn env
- `agora/worker_manager.py` — added `_inject_external_skills()` called during `create_worker`
- `agora/worker_templates.py` — added `_SELF_GROWTH_SECTION` appended by `render_soul()`
