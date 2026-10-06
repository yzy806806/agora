# Changelog

All notable changes to the Agora plugin are documented here.

## [2.0.10] — 2026-10-06

Two reports from a live downstream install, plus fixes from a review pass over
the v2.0.7..v2.0.9 delta.

### The completion gate failed open on an unreadable board

`check_project_complete` asked the board for pending work and treated a *failed
query* as an empty answer. SQLite lock contention is routine, and when the read
raised, the stop counter advanced toward `PROJECT_COMPLETE` with work still on
the board — the same failure mode as querying too few statuses. It now tracks
whether the board was actually read and defers otherwise, resetting any partial
progress. Also collapses six `COUNT` queries into one `GROUP BY`.

### The dashboard shim left the module spec behind (#3 follow-up)

v2.0.8's shim set `__package__` but not the matching `__spec__`, so every
relative import emitted `DeprecationWarning: __package__ != __spec__.parent` on
Python 3.14+ — which becomes an error on a later interpreter. `parent` is a
read-only property derived from `name`, so the spec is renamed to match;
`__name__` and the `sys.modules` key are untouched because pydantic/FastAPI
resolve the module's string annotations through `__name__`.

### Heartbeats stacked duplicate leaders (#6)

`heartbeat()` spawned unconditionally, so a leader whose run outlasted the cron
interval (20+ minutes under model contention) got another leader on top of it —
reported as ten concurrent leaders for one project, all holding connections to
the same endpoint. The project JSON stored `last_heartbeat_pid` but nothing read
it.

Now `live_heartbeat_pids()` prunes exited PIDs and returns the running ones, and
`update_heartbeat_status()` records each spawned PID into that list (append +
prune rather than a single slot, since two leaders can overlap momentarily and
dropping a live PID early is what caused the pileup). All three heartbeat paths
gate on it and return `skipped_in_flight`.

The gate fails **open**: a redundant leader wastes a slot, while a gate that
wrongly reports "in flight" leaves the project with no leader at all. The
script-level `flock` is not a substitute — it only guards the `Popen` call,
which returns immediately while the leader runs detached.

### Tasks could be assigned to roles that do not exist (#4)

`agora_create_task` wrote an unknown role string to the task verbatim
(`get_assignee_for_role` returns `None` and the original value was kept), so the
dispatcher spawned a profile that does not exist: the worker crashed, re-spawned,
and the task stayed `running` forever. An assignee that is neither a role nor a
worker on the team is now refused with the valid roles in the hint. A concrete
worker name and an omitted assignee still pass.

### Smaller

- `update_project_agents_md` no longer discards a failed Kanban Summary
  silently — a dropped summary renders identically to a clean board.
- The test suite's editable-finder patch looks the finder up by module name
  instead of "the first module exposing a MAPPING dict".

**Tests:** 77 passing. Three of the new ones fail on v2.0.9.

## [2.0.9] — 2026-10-06

### The completion gate skipped pending work, so a project could stop mid-discussion

Reported in #5 by @Tanju42. `check_project_complete` asked the board for three
statuses (`running`, `ready`, `blocked`) and ignored the rest — `todo`,
`triage`, `review` were all invisible. An in-progress motion lives in `todo`
(Hermes' `initial_task_state` resolves a child of a non-`done` parent to `todo`,
and motions hang off the chat root), so a leader could see a "clean" board and
declare the project complete while discussion was still running.

Three sites were affected, all now derived from one constant
(`agora.utils.PENDING_TASK_STATUSES`):

- `agora/leader_loop.py::check_project_complete` — the gate that rejects
  `PROJECT_COMPLETE` while work remains;
- `project_planner.py::_has_pending_tasks` — the same question for the leader's
  task list (it had `todo` but not `triage`/`review`);
- `project_planner.py::update_project_agents_md` — the **Kanban Summary the
  leader actually reads**. It listed running/ready/review/blocked/done, so
  in-flight motions never appeared in its own view of the board.

The pending set is every non-terminal status **except `scheduled`**: Agora parks
its per-project chat-root anchor there permanently, and counting it would have
pinned every project at "not complete" forever. The issue's suggested fix
(`running, ready, todo, triage, review, blocked`) is right about which statuses
carry work, but its terminal list named `cancelled`, which is not a Hermes
status — the terminal statuses are `done` and `archived`. Four regression tests
cover both directions: pending work must block the gate, and the parked anchor
must not.

**Tests:** 71 passing.

## [2.0.8] — 2026-10-05

### Dashboard shim: drop sys.path mutation, reuse package registration pattern

Per upstream review (#132991): the v2.0.7 shim put the plugin root on
``sys.path`` and imported a bare ``agora`` module — both work but are not how
the gateway loads the plugin. Rewrote to match the ``agent_spawn.py`` runner
pattern: register ``hermes_plugins`` (namespace) and ``hermes_plugins.agora``
(with ``__path__``) in ``sys.modules``, set ``__package__`` to
``"hermes_plugins.agora.dashboard"``. No ``sys.path`` change, no bare
top-level module.

### conftest: stop writing to the editable finder file

Per upstream review (non-blocking, but applied): the finder auto-patch now
patches the in-memory MAPPING dict only. It does NOT ``write_text`` the
Hermes editable-install finder file — the stale file is an upstream issue and
writing to it from a test suite has side effects on the host install.

**Tests:** 65 passing. `hermes plugins validate`: exit 0, 13/13, security safe.

## [2.0.7] — 2026-10-05

### Dashboard tab was empty — 500 on every endpoint

The Hermes **dashboard** loader imports ``plugin_api.py`` as a top-level module
(``spec_from_file_location`` with empty ``__package__``), while the **gateway**
imports it as part of the ``hermes_plugins.agora`` package. Every relative import
(``from ..agora.team_manager import …`` — 38 sites) that resolves fine in the
gateway raises ``ImportError: attempted relative import with no known parent
package`` in the dashboard, so every ``/api/plugins/agora/*`` endpoint returned
500 and the tab rendered empty ("No teams / No projects").

Fix: a compatibility shim at the top of ``plugin_api.py`` detects the
no-package-context case, resolves the plugin root, puts it on ``sys.path``, and
restores ``__package__`` to ``"agora.dashboard"``. In the gateway context
``__package__`` is already set, so the shim is a no-op. No call sites changed.

Reported in #3 by @Tanju42 (an AI agent diagnosing a live install). The issue
included a correct analysis and a two-part fix (shim + convert 38 imports to
absolute); this release uses a more surgical approach — one shim, zero import
changes — achieving the same result with less surface area.

**Tests:** 58 passing (test_hardening +1: loads plugin_api as the dashboard does
and calls an endpoint that uses a relative import).

## [2.0.6] — 2026-09-30

### Tenant scoping completed: two more sites, and the kanban DB path

`tenant = ? OR tenant IS NULL` still appeared in two places after v2.0.4's sweep,
and the dashboard resolved its database through a hardcoded path. All three are
fixed, and the invariant is now enforced by a test.

- **`check_project_complete` counted foreign tasks.** The pending-task check that
  gates `PROJECT_COMPLETE` matched NULL tenants too, so an un-tenanted task on
  another board kept the project from ever completing. The stop mechanism
  requires a vote and then two consecutive clean heartbeats; this defeated both.
- **Dashboard counts and task lists mixed boards.** `_count_tasks` and the
  project task list included un-tenanted tasks, inflating other projects' numbers.
- **The dashboard read a hardcoded DB path.** `os.environ.get("HERMES_KANBAN_DB",
  str(Path.home() / ".hermes" / "kanban.db"))` — wrong on any install whose Hermes
  home is not `~/.hermes`, and it bypassed core's resolver entirely. Now defers to
  `hermes_cli.kanban_db.kanban_db_path()`, which resolves through `kanban_home()`
  (`HERMES_KANBAN_HOME`, else the default root — deliberately not the active
  profile's `HERMES_HOME`, since the board is shared across profiles and a
  profile-scoped path would fork it and break the dispatcher/worker handoff).

Two new tests keep this from regressing: one fails if any source line matches
`tenant IS NULL`, one asserts the dashboard's path equals core's resolution
(rather than merely looking plausible).

**Tests:** 64 passing.

## [2.0.5] — 2026-09-28

### Documentation-driven audit: board names and two scan traps

Rewriting `MODULE_DEPENDENCIES.md` from the source (rather than by hand) meant
extracting every import, path and environment read with an AST walker. Two things
that survived the code path for a long time fell out of that.

**Board names had more than one construction site**

The board (kanban tenant) for a project is `agora-<safe_name(project)>`, and
`safe_name()` rewrites spaces and `/`. Four places assembled the prefix directly
from the *raw* project name:

- `agora_create_task` — a task created with `project="My Project"` got tenant
  `agora-My Project` while the project's board is `agora-My_Project`.
- `stop_project`/restart cleanup and the status counters read from the task
  table, so such a task was **invisible** to project status, **not deleted** when
  the project stopped, and **refused** by `agora_close_task` (ownership check).
- The dashboard's task counts and board lookup had the same split.

All of them now go through `project_planner.agora_board_for`, the single
construction site, and a test asserts no literal `agora-` f-string comes back.

**A missing lazy import**

The dashboard's board lookup referenced `agora_board_for` without importing it in
that function's scope — a `NameError` on the project-detail route. The existing
tests do not exercise the dashboard, so nothing caught it; the static check does
now.

**One more self-inflicted security-scan trip**

`hermes plugins validate` fails the build on `agent_config_mod_shell`, which
matches `>` immediately before a path ending in `AGENTS.md`. An angle-bracket
placeholder is the natural way to write a path in a doc, and it trips the rule —
the file-paths table in the rewritten `MODULE_DEPENDENCIES.md` did. Reworded, and
a test now scans every shipped text file for the pattern so a documentation change
cannot silently fail the catalog CI (the same trap hit this project once before,
in `MODULE_DEPENDENCIES.md` and then in the changelog describing it).

### Two documented-but-inert paths (found by the catalog reviewer)

Both from the v2.0.4 round; reported by @teknium1 in #1 and fixed in that PR,
which this release merges.

- **`agora_start_project` never accepted `allow_unattended`.** The README, the
  `agora-setup` skill and the catalog Disclosure all tell users to call
  `agora_start_project(..., allow_unattended=True)`, but `_START_PROJECT_SCHEMA`
  had no such property and the handler never forwarded it — only the Dashboard's
  `POST /projects` body did. Anyone following the README got the default, i.e. a
  team that can read and discuss but cannot write files or run commands.
  The flag is now on the schema (boolean, default `false`) and passed through.
- **Bundled skills never deployed on project start.** `start_project` did
  `from .agora import deploy_bundled_skills` — the inner `agora/` subpackage,
  which does not define it. The `ImportError` was swallowed by the surrounding
  `except Exception`, so it logged a warning and did nothing. Since `register()`
  no longer deploys skills (see 2.0.4), that was the *only* automatic path left.
  Now `from . import deploy_bundled_skills`, and the surrounding handler
  distinguishes "no bundled skills" from a real failure.

### Tests are hermetic now

The board fixtures called `kanban_db.connect(board=…)`, whose path resolves from
`HERMES_KANBAN_DB` / the Hermes home. The suite therefore depended on the ambient
environment being writable and pre-created: on a machine where it is not, every
board fixture errored with "unable to open database file", and the failures looked
like real defects. An autouse fixture now pins `HERMES_KANBAN_DB` and
`HERMES_HOME` inside each test's tmp dir. Verified by running the suite with a
missing `HERMES_KANBAN_DB` parent, a read-only `HERMES_HOME`, and a read-only
`HOME` with no `HERMES_HOME` — all 62 pass in each.

The `conftest` bootstrap also now executes the plugin's `__init__.py` the way
Hermes' loader does, instead of registering a bare module: that is what exposes
package-level symbols, and its absence is how the wrong-package import above went
unnoticed by the suite.

**Tests:** 62 passing.

### `MODULE_DEPENDENCIES.md` rewritten

The document was five versions stale and described the pre-2.0 layout. It is now
generated from the source: the real import graph with module-level vs lazy edges,
the actual kanban symbol call sites, the subprocess table, every path read or
written (with the global-vs-active home distinction that the registries and the
cron job depend on), and the environment variables — including that `HERMES_HOME`
is never read directly, only resolved through `hermes_constants`. It documents the
one genuinely mutual import group (`project_planner` / `leader_loop` /
`team_manager`) and why those edges are lazy, plus the leaf modules that are safe
to extend. The regeneration procedure is at the end of the file.

**Tests:** 59 passing.

## [2.0.4] — 2026-09-28

### Catalog admission: review follow-up

Changes made in response to the plugin-catalog review, grouped by what the
reviewer flagged. Every item reached outside the plugin's own sandbox.

**Approvals are now opt-in**

- Workers and the leader no longer run with `--yolo --accept-hooks` by default.
  A `-q` subprocess has nobody to answer an approval prompt, so without the flag
  their flagged actions fail closed: the team can read, discuss and plan, but
  cannot write files or run commands.
- New `allow_unattended` flag on `agora_start_project` (default `False`, also
  exposed in the Dashboard) adds the bypass for one project. Stored in the
  project registry; opting in is explicit and never inherited by a restart.
- Chair/participant names from `agora_raise_motion` are now validated against
  the worker registry before they reach `hermes -p <name>`.

**Credentials**

- The worker profile's `.env` is **copied** instead of symlinked, matching core's
  profile provisioning (`hermes_cli/profiles.py::_clone_file`), and tightened to
  mode `0600` because `copy2` preserves the source's permission bits. A symlink
  let anything running in the worker profile read *and rewrite* the user's real
  keys through the link. Existing symlinks are migrated to copies.

**Registration no longer writes to disk**

- `register()` no longer deploys the bundled skills; that moved to an explicit
  `hermes agora setup` command (and still runs on `agora_start_project`).
- Skill deployment and worker seeding resolve paths through
  `hermes_constants.get_hermes_home()` instead of a hardcoded `Path.home()`, so a
  custom `HERMES_HOME` is respected instead of being written around.

**Kanban scope**

- Dropped `OR tenant IS NULL` from the task queries in `project_planner.py`.
  Those matches selected *every* un-tenanted task in the database, and `stop_project`
  / project-restart deleted them. Every task Agora creates sets a `tenant`, so
  the strict board scope is both correct and safe.
- `close_motion`'s raw `UPDATE tasks SET status='done'` now verifies the target is
  an Agora motion (title prefix `[Motion] `) before writing.
- `agora_close_task` refuses tasks that are not on an Agora project board.

**Imports and paths**

- Every module now reaches its siblings through relative imports inside the
  `hermes_plugins.agora` package. The plugin root is no longer inserted into
  `sys.path` — it contains `tools/`, `hooks/` and `skills/`, which core also has,
  so putting it there shadowed those packages.
- This also fixed a latent bug: `project_planner.py` had a module-level absolute
  import that only resolved when the dashboard happened to load first.
- Removed hardcoded install paths (`/usr/local/lib/hermes-agent`, `/root`,
  `/home/ubuntu`) from the binary lookup, the dashboard defaults, the heartbeat
  script and the discussion runner. Paths derive from `HERMES_HOME` /
  `sys.executable` at runtime.
- The generated heartbeat script and discussion runner load the plugin as
  `hermes_plugins.agora` (mirroring Hermes' own loader) so the relative imports
  resolve in those standalone processes.
- The discussion runner is spawned with `sys.executable` instead of a bare
  `python3`: the latter resolved to Hermes' bundled tool Python, which cannot
  import `hermes_cli`.

**Docs**

- `README.md` is now the English README and `README.CN.md` the Chinese one, so
  the catalog's English-first expectation is met. Content is otherwise unchanged.
- Documented the approvals model, the `hermes agora setup` step, and the
  `allow_unattended` opt-in in both READMEs and the `agora-setup` skill.
- Removed stale documentation: memory-tool dependency rows (memory writes were
  removed in 1.9.0), `.env` symlink references, and the 1.x `motions.db` schema
  is now marked legacy.

**Tests:** 56 passing (13 new, covering the boundaries above).

### Review pass on the above

A self-review of this release's diff caught three defects, all fixed here:

- **The generated heartbeat script did not parse.** `AGORA_PLUGIN_PATH="$PLUGIN" { … }`
  is not valid shell — the brace group was treated as a command named `{`, the
  `} 2>&1 | tail -10` was a syntax error, and the cron job's output was not
  tailed. Found by actually running the script rather than eyeballing it; now
  `export …` on its own line + a brace group, and covered by a test that runs
  `bash -n` on the generated script.
- **The motion ownership guard was too narrow.** Matching only the `[Motion] `
  title prefix meant a motion renamed outside Agora would be refused — and the
  driver finalizes through `close_motion`, so that path could break. The guard
  now accepts the title prefix **or** the motion-metadata comment.
- **The guard's `ValueError` escaped uncaught.** `_wrap_handler` does not catch
  exceptions, so `agora_close_motion` would surface a raw traceback instead of
  its usual `{"error": …}` shape. The handler now converts it.

Cleanups from the same pass: removed an unused `BUNDLED_SKILLS` constant and a
duplicated Hermes-home helper, dropped two `except Exception: pass` guards in
`find_hermes_binary` (neither call can raise), fixed a comment that still
described the removed `OR tenant IS NULL` query, and the heartbeat script now
prefers the interpreter that generated it over a bare `python3`.

## [2.0.3] — 2026-09-27

### Catalog admission: security-scan clean

`hermes plugins validate` exited 1 on two `dangerous` findings, which would
fail the plugin-catalog CI gate. Both are fixed:

- **invisible_unicode × 6** — the ZWJ (U+200D) inside the 👨‍💼 emoji tripped the
  scanner. Replaced with 👑 (single codepoint) in the leader template, the
  dashboard bundle, and both READMEs.
- **agent_config_mod_shell** — a docs line spelled the project context file's
  path with an angle-bracket workdir placeholder; the placeholder's closing
  bracket read as a shell redirect into that file. Reworded.

Verified: `hermes plugins validate` → exit 0, all 13 checks pass,
security scan: safe.

## [2.0.2] — 2026-09-27

### Docs rewrite + manifest fix (onboarding pass)

The README had drifted five versions behind and no longer matched the 2.0
architecture; several onboarding gaps made first-run confusion likely.

- **README rewritten in both languages, Chinese now the default.** `README.md`
  is Chinese (GitHub homepage default), `README_EN.md` is the English mirror —
  identical structure, with a language switcher at the top of each.
  `README_CN.md` removed.
- **New sections:** Prerequisites (Hermes + model config + gateway + workdir),
  "What to Expect Once It's Running" (heartbeat timing — the most common false
  alarm), Stop & Cleanup, Troubleshooting.
- **Corrected stale content:** version header (was v1.8.8), the three
  "motions database" references (2.0 is Kanban-backed), the tool list (18 → 20,
  now including `agora_message` / `agora_read_chat`), and the architecture tree
  (`motions_kanban.py` + `chat.py` / `motion.py` / `execution.py` /
  `kanban_compat.py`).
- **Inline changelog removed from the README** and the 14 versions it held that
  were missing from `CHANGELOG.md` (v1.4.0–v1.8.0) were merged into it, so
  `CHANGELOG.md` is now the single source (32 versions, 1.0.0 → 2.0.2).
- **`plugin.yaml` manifest fix:** it declared 18 tools while the code registers
  20 — `agora_update_project` and `agora_close_task` were missing. The manifest
  now matches the implementation exactly.
- **Bundled skills corrected:** `agora-setup` (prerequisites, heartbeat
  expectation, troubleshooting entries for the dashboard tab / provider error /
  429s), `agora-awareness` (removed the stale MEMORY.md claim), and
  `agora-deliberation` (motion ids are Kanban task ids; the conclusion goes to
  `task.result`, not MEMORY.md).

## [2.0.1] — 2026-09-18

### Post-release review fixes

- `session_manager._heuristic_activity_count` called `_agora_db_path()` on the
  Kanban backend, which has no such method — the motions-DB message count was
  silently returning 0 (dead branch). Removed it; the Kanban done-task count is
  the correct 2.0 activity proxy.
- `motion.create_motion` dropped the 1.x `source` field (user vs agent), which
  the rescue/`_find_motion_for_task` path relies on. Added `source` to the
  motion metadata and threaded it through `motions_kanban.create_motion`.

## [2.0.0] — 2026-09-17

### Unified discussion & execution engine (built on Hermes Kanban)

Agora 2.0 removes the split between discussion (motions.db) and execution
(kanban) — both now live on Kanban. A motion is a sub-task of a persistent
team chat root; speech and votes are `[agora:msg]` comments; the conclusion
lands in `task.result`; and adopted conclusions become execution tasks
automatically with the motion as parent, so context flows by Hermes' native
parent-handoff instead of leader transcription.

**M1 — unified chat bus** (`agora/chat.py`)
- Chat root = persistent Kanban task pinned `scheduled` (never dispatchable,
  never completes). Messages are `[agora:msg]` JSON comments. Per-worker
  unseen tracking reuses Hermes notify-subscription cursors under
  `platform="agora"` (gateway notifier skips them; Agora owns the pull).
- `agora_message` / `agora_read_chat` tools. Fire-and-forget; no fan-out.

**M2 — motion threading** (`agora/motion.py`)
- Motion = Kanban sub-task; deterministic sparse scheduler (`next_speaker`:
  @mention priority, then round-robin — not AutoGen's per-turn selector).
- Conclusion written to `task.result` via direct done-flip (the chat root is
  `scheduled`, so `complete_task`'s parent gate would refuse).
- 0-speech `adopted` guard retained (downgrades to `error`).

**M3 — discussion↔execution converter** (`agora/execution.py`)
- `motion_to_tasks`: action items → tasks with `parents=[motion_id]`.
- `blocked_to_motion`: a blocked task raises a motion depending on it;
  `kanban_task_blocked` hook now uses this path.

**M4 — lean leader**
- Leader SOUL.md + heartbeat prompt: Assess/Discuss/Arbitrate (dropped
  Assign/Verify). No manual task transcription.

**M5 — dashboard viz**
- `GET/POST /projects/{name}/chat` + `GET /projects/{name}/motions`.

**Review fixes**
- `chat.rewind_unseen` passed `cursor=` but `rewind_notify_cursor` takes
  `claimed_cursor`+`old_cursor` — would TypeError on retry. Fixed.
- `motion._result_field` crashed on non-dict `task.result` (e.g. valid JSON
  scalar). Fixed.
- `kanban_compat` bridge extended for notify symbols moved in the Sept
  decomposition.

**Tests:** 36/36 pass (13 new: chat, motion, execution).

## [1.9.2] — 2026-09-05

### Hermes September-2026 decomposition compatibility (PR #102117)

`hermes_cli.kanban_db` was split into focused submodules
(`kanban_db_connect`, `kanban_db_dispatch`, ...). Hermes ships a temporary
compat layer re-exporting the moved names, **removed on 2026-09-14** — after
that date Agora v1.9.1 fails to load with `AttributeError: connect`.

**Fix:** new `agora.kanban_compat` module resolves `kanban_db` symbols
against the new submodule locations first, falling back to the legacy module
for older Hermes versions. All 20 `from hermes_cli import kanban_db` import
sites across 7 files (hooks, tools, leader_loop, session_manager, driver,
project_planner, dashboard/plugin_api) now go through the bridge.

Verified against Hermes v0.20.x post-decomposition: `connect` resolves from
`hermes_cli.kanban_db_connect` with **zero** compat warnings; all other
symbols used by Agora (`complete_task`, `delete_archived_task`, review
lifecycle APIs, `VALID_STATUSES`, `_append_event`) remain defined in
`kanban_db` proper and are untouched.

Other contracts re-verified post-decomposition: hook names
(`kanban_task_completed/claimed/blocked`), cron CLI flags
(`--name --no-agent --script --deliver`), dashboard plugin API mounting
(`kind: backend`, `api: plugin_api.py` router contract), `profiles`
module surface, and `PluginContext.register_tool/register_hook/
register_cli_command` — all unchanged.

## [1.9.1] — 2026-08-14

### Second OCR audit: robustness + dead code cleanup

**C1. 429 error detection false positives fixed**
`_speaker_speak` and `_spawn_with_retry` matched bare `"429"` in replies —
any discussion message mentioning "line 429" or "port 429" triggered a
spurious retry. Now matches only deterministic error phrases:
`api call failed`, `rate limit`, `rate_limit`, `authorization failed`,
`http 429`, `http 503`.

**H1. patch_config_model rewritten with yaml.safe_load**
Previously used regex string substitution on config.yaml — fragile against
indentation, comments, and anchors. Now uses structured
`yaml.safe_load`/`yaml.safe_dump`, consistent with
`ensure_in_place_compression`.

**H2. Session rotation thresholds raised for lean-tail compression**
v0.20.6 defaults to lean-tail compression which handles context management
intelligently. Old thresholds (`500` messages / `2000` KB) caused premature
rotation that lost context. Raised to `2000` messages / `8000` KB.

**H3. Leader session dead code removed**
Leader uses fresh session every heartbeat (no `--resume`), but
`get_leader_session`/`set_leader_session` functions, the
`leader_session_id` JSON field (3 write sites), and the
`set_leader_session` call in leader_loop.py were all still present.
All removed.

**H4. Dashboard task list now filters by tenant**
`/projects/{name}/tasks` returned tasks from ALL projects. Now filters
with `tenant = ? OR tenant IS NULL` (same pattern as AGENTS.md generation).

**M2 + L2. Minor cleanups**
- `team_manager.py`: removed unused `import os` (dead import)
- `hooks/__init__.py`: removed empty `if adopted: pass` block left from
  v1.9.0 memory cleanup

### Files changed
- `agora/discussion/driver.py` — 429 detection fixed in both retry paths
- `agora/utils.py` — patch_config_model rewritten with yaml
- `agora/session_manager.py` — rotation thresholds raised
- `project_planner.py` — leader session dead code removed
- `agora/leader_loop.py` — set_leader_session call removed
- `dashboard/plugin_api.py` — tenant filter added
- `agora/team_manager.py` — unused import removed
- `hooks/__init__.py` — empty pass block removed
- `__init__.py` / `plugin.yaml` — version bump

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

## [1.8.0] — Full code audit: motion guards, discussion quality, truncation fix, 20 bug fixes

Comprehensive code review (OCR standard mode + subagent audit) identified and fixed 20 issues across 7 files:

**Critical:**
- **`agora_close_motion` adopted guard** — cannot close a motion as "adopted" with 0 discussion steps or 0 messages. Prevents leader from bypassing the discussion engine.
- **File descriptor leak** — `log_fd` opened per heartbeat but never closed in parent process. Now closed after `Popen`.
- **Discussion min_steps floor** — chair can no longer close/vote before `max(3, len(participants))` steps. Ensures every participant gets at least one turn.

**High:**
- **Motion threshold guidance** — SOUL.md now has explicit "Do NOT raise a motion for" list (routine assessment, stale cleanup, duplicate topics, recent stop-condition checks).
- **Stop condition cooldown** — heartbeat prompt includes complete_count reminder to prevent re-evaluation.
- **`_has_pending_tasks` includes blocked** — was excluding blocked tasks, causing premature "all done" signals.
- **Tenant strip bug** — `replace("agora-", "")` → `removeprefix("agora-")` to avoid stripping interior matches.
- **`_infer_stance` oppose matching** — substring match → regex word boundary, same as support check.
- **`agora_close_task` missing commit** — `conn.commit()` added before `conn.close()`.
- **chair.py f-string injection** — literal curly braces in user input no longer cause KeyError.
- **utils.py model regex escape** — `re.escape(model)` added.
- **reactivate cron HERMES_HOME** — already fixed in v1.7.0, confirmed applied.

**Medium:**
- **Output truncation 2000→8000** — discussion context, task context, and task body all increased from 2000 to 8000 chars.
- **`_build_history` per-message 500→1000** — more context for chair evaluation.
- **Unused `Optional` import** removed from driver.py.
- **`max_steps=0` edge case** guarded.
- **`max_steps` default detection** uses None sentinel instead of `== 30`.
- **Misleading tool count log** corrected.
- **`except Exception: pass`** → `logger.warning(...)` in 5 critical locations.
- **reactivate validates `heartbeat_member`** before proceeding.
- **Stale cleanup timestamp** added to avoid running every heartbeat.

## [1.7.1] — Post-Task Skill Review: mandatory skill creation in worker SOUL.md

- **Root cause of 0 self-created skills identified**: Hermes' background skill review runs as a daemon thread *after* the turn completes, but worker processes (`hermes -p <profile> --cli chat -Q -q "..."`) exit immediately after the task, killing the thread before it can run.
- **Fix: Post-Task Skill Review section in SOUL.md** — all worker roles now have a mandatory "Before calling `kanban_complete`, review your work for reusable knowledge" step. Workers create skills *during* the task turn using `skill_manage(action='create')`, not after via a background thread.
- Updated `worker_templates.py` (`render_soul` now appends `_POST_TASK_SKILL_REVIEW` to every role) and all 7 deployed SOUL.md files.
- Cleaned motion record garbage from reviewer/architect/researcher/writer memory (40KB → <1KB total).

## [1.7.0] — Discussion speaker tool access + chair retry + task management

- **Discussion speakers now have full tool access** — changed `--toolsets agora` to `--toolsets hermes-cli` in `agent_spawn.py`. Previously, discussion participants (architect, developer, researcher, tester, reviewer, writer) only had the 17 Agora tools — no `terminal`, `read_file`, `search_files`, `web_search`, `web_extract`. This caused 112+ messages across two projects where workers reported they couldn't read code, run tests, or research reference projects. Now speakers have all built-in tools + Agora tools. *(Note: In v1.8.6, this was further refined — speakers now use the worker template toolsets: `terminal, file, web, skills, todo, session_search`, not the full `hermes-cli`.)*
- **Chair open/evaluate retry on non-JSON** — when the chair (leader) returns a non-JSON response, the discussion driver retries once with a stronger "respond with JSON ONLY" prompt before aborting. Prevents `decision=error, steps=0` motions caused by occasional LLM formatting failures.
- **`spawn_discussion_driver` uses global `~/.hermes/agora/`** — runner scripts and log files now always go to the global agora directory, not the profile-scoped `HERMES_HOME`. Fixes the issue where leader heartbeat created runner scripts in `~/.hermes/profiles/leader/agora/` but they couldn't be found by other processes.
- **Stuck motion auto-cleanup** — motions stuck at `steps=0` for more than 5 minutes are now automatically closed as `error` by `_rescue_stuck_motions`. Previously these stayed in `discussing` forever, blocking leader from closing them.
- **Kanban task counts filtered by tenant** — `_count_tasks()` now accepts a `tenant` parameter. Dashboard project list and detail views show per-project task counts instead of global totals. Fixes "kanban count not resetting" for new projects.
- **New `agora_close_task` tool** — leader can now close stale blocked/running tasks directly (action=`complete` or `cancel`) without needing kanban CLI or `HERMES_KANBAN_TASK` env var. SOUL.md updated with stale task cleanup instructions. *(In v1.8.6, a `submit_review` action was added for code review workflow.)*
- **`complete_count` initialized on new project** — new projects now start with `complete_count: 0` and `completion_check_pos: 0` instead of `None`.
- **Researcher SOUL.md strengthened** — researcher must use `web_search`, `web_extract`, `terminal`, and `read_file` to investigate topics. Cannot rely on memory alone. Must read reference project source code before giving recommendations.

## [1.6.2] — Leader fresh session + AGENTS.md enhancement + kanban gate

- **Leader uses fresh session every heartbeat** — no more `--resume`. Accumulated session history caused attention degradation: leader repeated already-completed motions, ignored SOUL.md constraints, claimed "no running tasks" without checking. Context now comes entirely from AGENTS.md + MEMORY.md + SOUL.md.
- **AGENTS.md enhanced** — now includes Kanban Summary (running/ready/blocked/done counts + task list), Last heartbeat timestamp, and Recent Decisions (last 3 adopted motions). Gives fresh-session leader full project state.
- **PROJECT_COMPLETE kanban gate** — `check_project_complete` now queries kanban by tenant before counting PROJECT_COMPLETE. If running/ready/blocked tasks exist, rejects with `[SYSTEM] PROJECT_COMPLETE rejected` message in log. Multi-project safe (tenant-filtered).
- **Cleaned worker memory** — 5 workers had ~34K chars of stale motion records (pre-v1.4.7 hooks). Cleaned to only retain technical experience.

## [1.6.1] — Code audit fixes + task creation guardrails

- **`start_project` reactivate now detects stale cron** — same stale-detection logic as `update_project`: verifies cron_id against `hermes cron list` before reuse.
- **`stop_project` / `on_project_complete` clear `heartbeat_cron_id`** — previously deleted the cron job but left the stale ID in project JSON, causing reactivate to skip cron creation.
- **Task creation guardrails in SOUL.md + heartbeat prompt** — leader must check existing tasks before creating new ones (prevent duplicates); must never assign tasks to self (leader is facilitator, not implementer).
- **Fixed tool count in log** — 16 → 17 (agora_update_project added in v1.5.0).

## [1.6.0] — Reactivate fix: reset completion state + heartbeat prompt

- **Reactivate now resets `complete_count`, `leader_session_id`, `completion_check_pos`** — Previously, reactivating a completed project left stale completion state. Leader would read old memory, see complete_count > 0, and immediately output PROJECT_COMPLETE without evaluating the new goal.
- **Heartbeat prompt warns about goal changes** — Added "If the goal or stop condition has changed since your last heartbeat, treat this as a NEW project phase. Do NOT carry over previous PROJECT_COMPLETE decisions."
- **Reactivate verifies cron job existence** — Checks `hermes cron list` to detect stale cron IDs (deleted during PROJECT_COMPLETE but still in project JSON).
- **`start_project` preserves existing project data** — No longer overwrites all fields when project already exists (from v1.5.9, now also in reactivate path).
- **Schema expanded** — `agora_start_project` now accepts `description`, `stop_condition`, `team`. `workdir` no longer required for existing projects.
- **Verified end-to-end** — Reactivated docmind project with new goal, leader correctly identified new phase, raised motions, team discussed and adopted, tasks being assigned.

## [1.5.9] — Fix start_project overwriting existing project data

- **`agora_start_project` no longer overwrites existing projects** — if a project already exists, it preserves all fields (team, goal, stop_condition, heartbeat_member, etc.) and only reactivates. Previously, calling `start_project` on an existing project would reset everything to defaults.
- **Schema expanded** — added `description`, `stop_condition`, `team` parameters. `workdir` is no longer required (preserved from existing project). All new params only override if non-empty.
- **Heartbeat cron auto-recreated** — if a reactivated project has `heartbeat_member` but no `heartbeat_cron_id`, the cron job is automatically recreated.

## [1.5.8] — Dashboard project settings UI

- **Project Settings panel** in dashboard Overview tab — edit goal and stop_condition inline, reactivate completed/stopped projects with one click. Calls `PUT /api/plugins/agora/projects/{name}`.
- Added `agora-form-field` and `agora-input` CSS classes.

## [1.5.7] — Hermes v0.18.2 compatibility fix

- **`kanban_db.add_comment` signature changed** — now requires `author` parameter. Updated all 3 call sites in hooks.
- Compatibility verified against Hermes v0.18.2 (2026.7.7.2):
  - `ctx.register_tool` / `register_hook` / `register_cli_command` — unchanged ✅
  - kanban hooks (claimed/completed/blocked) — still in VALID_HOOKS ✅
  - `_normalize_handler_result` requires str — Agora uses `_wrap_handler` ✅
  - `Task` class fields (tenant, body, assignee, started_at, completed_at) — unchanged ✅
  - `create_task` / `block_task` / `get_task` — backward compatible ✅
  - AGENTS.md context file loading — unchanged ✅

## [1.5.6] — Timeout unification + tool handler fix + dashboard emoji + onboarding

- **All LLM timeouts unified to 1 hour (3600s)** — speak_timeout, chair_timeout, vote, dispatch, spawn defaults. Removed `min(speak_timeout, 240)` cap. Local models with long context preprocessing need generous timeouts.
- **Tool handler return type fix** — Hermes registry requires `str` (JSON), not `dict`. Added `_wrap_handler` / `_wrap_handler_async` at module level. All 17 tools now register and return correctly.
- **Dashboard emoji encoding** — JS byte escapes (`\xF0\x9F`) → Unicode escapes (`\uXXXX`). Fixed garbled `ð` → `👑`.
- **agora-setup skill** — New onboarding skill for operators (step-by-step: create workers, form teams, start projects).
- **Dead code cleanup** — Removed `_build_active_motions_summary()` (superseded by AGENTS.md).

## [1.5.2] — AGENTS.md as single source of truth + project updates

- **AGENTS.md** now contains: goal, stop_condition, team members (name → role template), active discussions. Written atomically (temp + rename). Refreshed on: start_project, heartbeat, project update, motion create/close.
- **Heartbeat prompt simplified** — 6 lines, no more inline context injection. All context via AGENTS.md auto-load.
- **`agora_update_project` tool** — change goal/stop_condition mid-flight. `reactivate=true` restarts completed projects.
- **Motion memory cleanup** — decision records only written to leader's MEMORY.md, not workers. Workers keep their own technical experience.
- **Skill creation nudge** — complex tasks (>1 run or >30min) get a kanban comment prompting the worker to save reusable workflows.
- **17 tools** (added `agora_update_project`).

## [1.4.4–1.4.6] — Code audit fixes

- Chair prompt: prevent false truncation calls
- Driver: MAX_SAME_SPEAKER=2 hard limit
- `_has_pending_tasks()` now accepts project_name with tenant filter
- SQLite busy_timeout=5000 for concurrent safety
- `_find_project_for_task()` uses task.tenant instead of string matching
- Worker session JSON uses fcntl.flock for concurrent safety
- Stale discussion_state cleanup on every heartbeat
- Session manager queries profile-specific state.db
- 15 issues fixed across 3 releases

## [1.4.3] — Discussion state consistency and stale motion recovery

- `discussion_state` cleaned on close
- Stuck discussions with messages recovered
- `agora_close_motion` tool added
- Speaker session preserved on timeout
- Timeout increased (900s/300s)

## [1.4.0–1.4.2] — Discussion engine reliability

- Session-not-found recovery
- Empty tool argument handling
- Stale memory poisoning fix
- Dead session cleanup
- Code cleanup and hardcoded path fixes

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
