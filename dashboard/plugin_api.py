"""Agora dashboard plugin — backend API routes.

Mounted at /api/plugins/agora/ by the Hermes dashboard plugin system.

Provides REST endpoints for:
  - Profile management (list, delete, config, SOUL, skills)
  - Worker management (list, create, remove, templates)
  - Team management (list, create, remove)
  - Project management (list, start, stop, heartbeat control)
  - Motion management (list, show, state, discuss)
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

try:
    from fastapi import APIRouter, HTTPException, Query
    from pydantic import BaseModel, Field
except ImportError:
    APIRouter = None  # type: ignore

if APIRouter:
    router = APIRouter(tags=["agora"])
else:
    router = None  # type: ignore

logger = logging.getLogger(__name__)

import sys as _sys
from pathlib import Path as _Path
_PLUGIN_ROOT = _Path(__file__).parent.parent
if str(_PLUGIN_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_PLUGIN_ROOT))

# ---------------------------------------------------------------------------
# Profile management (generic Hermes profile CRUD — not Agora-specific)
# ---------------------------------------------------------------------------

class UpdateProfileConfigRequest(BaseModel):
    model: Optional[str] = None
    provider: Optional[str] = None
    enabled_toolsets: Optional[list[str]] = None
    disabled_toolsets: Optional[list[str]] = None

class UpdateSoulRequest(BaseModel):
    content: str = Field(..., description="New SOUL.md content")

class UpdateSkillsRequest(BaseModel):
    skills: list[str] = Field(..., description="List of skill names to enable")


def _get_profiles_module():
    from hermes_cli import profiles
    return profiles


@router.get("/profiles")
def list_profiles():
    """List all Hermes profiles with their config summary."""
    try:
        profiles_mod = _get_profiles_module()
        infos = profiles_mod.list_profiles()
        return {
            "profiles": [
                {
                    "name": p.name,
                    "path": str(p.path),
                    "is_default": p.is_default,
                    "model": p.model,
                    "provider": p.provider,
                    "has_env": p.has_env,
                    "skill_count": p.skill_count,
                    "gateway_running": p.gateway_running,
                    "description": p.description,
                    "description_auto": p.description_auto,
                }
                for p in infos
            ]
        }
    except Exception as exc:
        logger.error("list_profiles failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/profiles/{name}")
def delete_profile(name: str):
    """Delete a Hermes profile."""
    try:
        profiles_mod = _get_profiles_module()
        profiles_mod.delete_profile(name, yes=True)
        return {"name": name, "deleted": True}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("delete_profile failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/profiles/{name}/config")
def get_profile_config(name: str):
    """Get a profile's config.yaml (model, provider, toolsets)."""
    try:
        profiles_mod = _get_profiles_module()
        profile_dir = profiles_mod.get_profile_dir(name)
        if not profile_dir.exists():
            raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

        config_path = profile_dir / "config.yaml"
        config = {}
        if config_path.exists():
            import yaml
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}

        model_cfg = config.get("model", {})
        if isinstance(model_cfg, str):
            model = model_cfg
            provider = None
        elif isinstance(model_cfg, dict):
            model = model_cfg.get("default") or model_cfg.get("model")
            provider = model_cfg.get("provider")
        else:
            model = None
            provider = None

        toolsets = config.get("toolsets", [])
        agent_cfg = config.get("agent", {})
        disabled_toolsets = agent_cfg.get("disabled_toolsets", [])

        return {
            "name": name,
            "model": model,
            "provider": provider,
            "toolsets": toolsets,
            "disabled_toolsets": disabled_toolsets,
            "config_path": str(config_path),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_profile_config failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/profiles/{name}/config")
def update_profile_config(name: str, req: UpdateProfileConfigRequest):
    """Update a profile's config.yaml (model, provider, toolsets)."""
    try:
        profiles_mod = _get_profiles_module()
        profile_dir = profiles_mod.get_profile_dir(name)
        if not profile_dir.exists():
            raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

        config_path = profile_dir / "config.yaml"
        import yaml
        config = {}
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}

        # Update model
        if req.model is not None or req.provider is not None:
            model_cfg = config.get("model", {})
            if not isinstance(model_cfg, dict):
                model_cfg = {"default": model_cfg} if model_cfg else {}
            if req.model is not None:
                model_cfg["default"] = req.model
            if req.provider is not None:
                model_cfg["provider"] = req.provider
            config["model"] = model_cfg

        # Update toolsets
        if req.enabled_toolsets is not None:
            config["toolsets"] = req.enabled_toolsets
        if req.disabled_toolsets is not None:
            agent_cfg = config.get("agent", {})
            if not isinstance(agent_cfg, dict):
                agent_cfg = {}
            agent_cfg["disabled_toolsets"] = req.disabled_toolsets
            config["agent"] = agent_cfg

        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

        return {"name": name, "updated": True, "config": config}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("update_profile_config failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/profiles/{name}/soul")
def get_profile_soul(name: str):
    """Get a profile's SOUL.md content."""
    try:
        profiles_mod = _get_profiles_module()
        profile_dir = profiles_mod.get_profile_dir(name)
        soul_path = profile_dir / "SOUL.md"
        content = ""
        if soul_path.exists():
            content = soul_path.read_text()
        return {"name": name, "content": content, "path": str(soul_path)}
    except Exception as exc:
        logger.error("get_profile_soul failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/profiles/{name}/soul")
def update_profile_soul(name: str, req: UpdateSoulRequest):
    """Update a profile's SOUL.md content."""
    try:
        profiles_mod = _get_profiles_module()
        profile_dir = profiles_mod.get_profile_dir(name)
        if not profile_dir.exists():
            raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

        soul_path = profile_dir / "SOUL.md"
        soul_path.write_text(req.content)
        return {"name": name, "updated": True, "path": str(soul_path)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("update_profile_soul failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/profiles/{name}/skills")
def get_profile_skills(name: str):
    """List skills available to a profile.

    Scans the profile-local skills/ directory plus any external_dirs
    configured in the profile's config.yaml. Skills listed in
    skills.disabled are filtered out.
    """
    try:
        import yaml as _yaml
        from pathlib import Path as _Path

        profiles_mod = _get_profiles_module()
        profile_dir = profiles_mod.get_profile_dir(name)
        if not profile_dir.exists():
            raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

        # Read disabled list and external_dirs from the profile's config.yaml
        config_path = profile_dir / "config.yaml"
        disabled: set[str] = set()
        external_dirs: list[_Path] = []
        if config_path.exists():
            with open(config_path) as f:
                cfg = _yaml.safe_load(f) or {}
            skills_cfg = cfg.get("skills", {})
            if isinstance(skills_cfg, dict):
                disabled = set(skills_cfg.get("disabled", []) or [])
                for d in (skills_cfg.get("external_dirs") or []):
                    p = _Path(d)
                    if p.is_dir():
                        external_dirs.append(p)

        def _parse_skill_name(md_path: _Path) -> str:
            """Extract the frontmatter 'name' field, fall back to dir name."""
            try:
                content = md_path.read_text(encoding="utf-8")[:2000]
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end > 0:
                        fm = content[3:end]
                        for line in fm.split("\n"):
                            line = line.strip()
                            if line.startswith("name:"):
                                return line.split(":", 1)[1].strip().strip("\"'")
            except Exception:
                pass
            return md_path.parent.name

        skills = []
        seen_names: set[str] = set()

        # Scan local dir first, then external dirs (local takes precedence)
        dirs_to_scan = [profile_dir / "skills"] + external_dirs
        for scan_dir in dirs_to_scan:
            if not scan_dir.is_dir():
                continue
            for sf in sorted(scan_dir.rglob("SKILL.md")):
                skill_name = _parse_skill_name(sf)
                dir_name = sf.parent.name
                # Check both frontmatter name and dir name against disabled
                if skill_name in disabled or dir_name in disabled:
                    continue
                if skill_name in seen_names or dir_name in seen_names:
                    continue
                seen_names.add(skill_name)
                seen_names.add(dir_name)
                rel = str(sf.parent.relative_to(scan_dir))
                skills.append({
                    "name": rel,
                    "skill_name": skill_name,
                    "path": str(sf),
                    "source": "local" if scan_dir == profile_dir / "skills" else "external",
                })

        return {"name": name, "skills": skills, "count": len(skills)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_profile_skills failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Motion management (thin wrappers around agora storage)
# ---------------------------------------------------------------------------

@router.get("/motions")
def list_motions(
    status: str = Query("all", pattern="^(active|closed|all)$"),
    limit: int = Query(20, ge=1, le=200),
):
    """List Agora discussions."""
    try:
        from agora.storage import motions as db
        motions = db.list_motions(status_filter=status, limit=limit)
        return {
            "motions": [
                {
                    "motion_id": m["id"],
                    "title": m["title"],
                    "status": m["status"],
                    "current_round": m["current_round"],
                    "max_rounds": m["max_rounds"],
                    "decision": m.get("decision"),
                    "source": m.get("source"),
                    "source_task_id": m.get("source_task_id"),
                    "project": m.get("project", ""),
                    "state": m.get("state", "discussing"),
                    "step_count": m.get("step_count", 0),
                    "chair": m.get("chair", ""),
                    "created_at": m.get("created_at"),
                }
                for m in motions
            ],
            "total": len(motions),
        }
    except Exception as exc:
        logger.error("list_motions failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/motions/{motion_id}")
def get_motion(motion_id: str):
    """Get a motion with all its messages."""
    try:
        from agora.storage import motions as db
        motion = db.get_motion(motion_id)
        if motion is None:
            raise HTTPException(status_code=404, detail="Motion not found")
        messages = db.get_messages(motion_id)
        return {
            "motion_id": motion_id,
            "title": motion["title"],
            "status": motion["status"],
            "current_round": motion["current_round"],
            "max_rounds": motion["max_rounds"],
            "decision": motion.get("decision"),
            "rationale": motion.get("rationale"),
            "action_items": motion.get("action_items", []),
            "source": motion.get("source"),
            "chair": motion.get("chair", ""),
            "messages": [
                {
                    "id": m["id"],
                    "role": m["role"],
                    "round_num": m["round_num"],
                    "stance": m["stance"],
                    "content": m["content"],
                    "timestamp": m["timestamp"],
                    "step_type": m.get("step_type", "speak"),
                    "is_chair": bool(m.get("is_chair", 0)),
                }
                for m in messages
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_motion failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Start a discussion from dashboard
# ---------------------------------------------------------------------------

class StartDiscussionRequest(BaseModel):
    title: str = Field(..., description="Discussion topic")
    description: str = Field("", description="Detailed description")
    participants: list[str] = Field(default=[], description="Worker profile names to participate")
    chair: str = Field("", description="Leader profile name as chair (auto-detected if empty)")
    project: str = Field("", description="Project name for team lookup")
    max_steps: int = Field(30, description="Max discussion steps")

@router.post("/motions")
def start_discussion(req: StartDiscussionRequest):
    """Create a motion and spawn the discussion driver as a background process.

    The driver runs event-driven: chair opens → speakers speak → chair evaluates → repeat.
    Each speaker is a real Hermes agent subprocess with full SOUL.md + MEMORY.md + tools.
    """
    try:
        import sys as _sys
        from agora.storage import motions as db

        # Auto-resolve participants and chair from the project
        participants = req.participants
        chair = req.chair
        max_steps = req.max_steps
        if not participants or not chair or max_steps == 30:
            if req.project:
                try:
                    from project_planner import get_heartbeat_member, get_project
                    from agora.team_manager import get_team
                    # Chair defaults to project's heartbeat_member
                    if not chair:
                        chair = get_heartbeat_member(req.project) or ""
                    # Participants + default_max_steps from the project's team
                    if not participants or max_steps == 30:
                        proj = get_project(req.project)
                        if proj and proj.get("team"):
                            team = get_team(proj["team"])
                            if team:
                                if not participants:
                                    participants = [w["name"] for w in team.get("workers", [])]
                                if max_steps == 30 and team.get("default_max_steps"):
                                    max_steps = team["default_max_steps"]
                except Exception as exc:
                    logger.warning("Project/chair lookup failed: %s", exc)

        if not participants:
            raise HTTPException(status_code=400, detail="No participants. Specify participants or provide a valid project with a team.")
        if not chair:
            raise HTTPException(status_code=400, detail="No chair specified. Provide chair or a project with a leader.")

        # Get workdir from project
        workdir = ""
        if req.project:
            try:
                from agora.utils import get_registry_dir, safe_name
                proj_file = get_registry_dir("projects") / f"{safe_name(req.project)}.json"
                if proj_file.exists():
                    import json as _json
                    proj = _json.loads(proj_file.read_text())
                    workdir = proj.get("workdir", "")
            except Exception:
                pass

        motion = db.create_motion(
            title=req.title,
            description=req.description,
            source="user",
            participants=participants,
            chair=chair,
            max_steps=max_steps,
            project=req.project,
        )

        # Spawn the discussion driver as a background process using the
        # shared spawn function (same logic used by the agora_raise_motion tool).
        try:
            from agora.discussion.agent_spawn import spawn_discussion_driver
            spawn_result = spawn_discussion_driver(
                motion_id=motion["id"],
                chair=chair,
                participants=participants,
                workdir=workdir,
                project_name=req.project,
                max_steps=max_steps,
            )
            if spawn_result.get("status") == "spawned":
                logger.info(
                    "Discussion driver spawned for motion %s (log=%s)",
                    motion["id"], spawn_result.get("log"),
                )
            else:
                logger.warning(
                    "Failed to spawn driver: %s (motion created, run manually)",
                    spawn_result.get("error", "unknown"),
                )
        except Exception as exc:
            logger.warning("Failed to spawn driver: %s (motion created, run manually)", exc)

        return {
            "motion_id": motion["id"],
            "title": req.title,
            "chair": chair,
            "participants": participants,
            "status": "discussing",
            "state": motion.get("state", "discussing"),
            "message": f"Motion created and discussion driver spawned. Chair: {chair}",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("start_discussion failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/motions/{motion_id}/state")
def get_discussion_state_endpoint(motion_id: str):
    """Get the current event-driven discussion state."""
    try:
        from agora.storage import motions as db
        motion = db.get_motion(motion_id)
        if motion is None:
            raise HTTPException(status_code=404, detail="Motion not found")
        state = db.get_discussion_state(motion_id)
        return {
            "motion_id": motion_id,
            "status": motion["status"],
            "state": motion.get("state", "discussing"),
            "step_count": motion.get("step_count", 0),
            "max_steps": motion.get("max_steps", 30),
            "chair": motion.get("chair", ""),
            "next_speaker": state.get("next_speaker") if state else None,
            "last_guidance": state.get("last_guidance") if state else None,
            "last_action": state.get("last_action") if state else None,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Worker management
# --------------------------------------------------------------------------- #

class UpdateProjectRequest(BaseModel):
    goal: Optional[str] = Field(None, description="New high-level goal")
    description: Optional[str] = Field(None, description="New project description")
    stop_condition: Optional[str] = Field(None, description="New stop condition")
    reactivate: bool = Field(False, description="Reactivate a completed/stopped project")


@router.put("/projects/{project_name}")
def update_project_endpoint(project_name: str, req: UpdateProjectRequest):
    """Update a project's goal, description, or stop condition."""
    try:
        from project_planner import update_project
        return update_project(
            project_name,
            goal=req.goal,
            description=req.description,
            stop_condition=req.stop_condition,
            reactivate=req.reactivate,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class CreateWorkerRequest(BaseModel):
    name: str = Field(..., description="Worker profile name")
    role: str = Field(..., description="Role: architect/developer/reviewer/tester/devops")
    clone_from: Optional[str] = Field(None)
    model: Optional[str] = Field(None)


@router.get("/workers")
def list_workers():
    """List all registered Agora workers."""
    try:
        from agora.worker_manager import list_workers as _list
        return {"workers": _list()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/workers/templates")
def list_worker_templates():
    """List available role templates."""
    try:
        from agora.worker_templates import list_templates
        return {"templates": list_templates()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/workers")
def create_worker(req: CreateWorkerRequest):
    """Create a worker profile from a role template."""
    try:
        from agora.worker_manager import create_worker as _create
        result = _create(name=req.name, role=req.role,
                         clone_from=req.clone_from, model=req.model)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/workers/{name}")
def remove_worker(name: str, delete_profile: bool = True):
    """Remove a worker from the Agora registry."""
    try:
        from agora.worker_manager import remove_worker as _remove
        result = _remove(name, delete_profile=delete_profile)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Team management
# --------------------------------------------------------------------------- #

class CreateTeamRequestV2(BaseModel):
    team_name: str = Field(...)
    workers: list[str] = Field(...)
    project: Optional[str] = Field(None)


@router.get("/teams")
def list_teams():
    """List all registered teams."""
    try:
        from agora.team_manager import list_teams as _list
        return {"teams": _list()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/teams")
def create_team(req: CreateTeamRequestV2):
    """Create a team by selecting workers."""
    try:
        from agora.team_manager import create_team as _create
        result = _create(team_name=req.team_name, worker_names=req.workers,
                         project=req.project)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/teams/{team_name}")
def remove_team(team_name: str):
    """Remove a team."""
    try:
        from agora.team_manager import remove_team as _remove
        result = _remove(team_name)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Project management (with heartbeat control)
# --------------------------------------------------------------------------- #

class StartProjectRequest(BaseModel):
    name: str = Field(..., description="Project name")
    goal: str = Field(..., description="Project goal")
    description: str = Field("", description="Detailed project description")
    stop_condition: str = Field("", description="When should the project stop?")
    workdir: str = Field("/root", description="Working directory")
    team: Optional[str] = Field(None, description="Team name")
    max_rounds: int = Field(10, description="Max planning rounds")
    heartbeat_member: Optional[str] = Field(None, description="Worker name to wake on heartbeat (usually a leader)")
    heartbeat_minutes: int = Field(15, description="Heartbeat interval in minutes")


class UpdateHeartbeatRequest(BaseModel):
    minutes: int = Field(..., description="New heartbeat interval in minutes")


def _count_tasks(tenant: str = "") -> dict:
    """Count tasks by status, optionally filtered by tenant (board name).

    Includes tasks with NULL tenant — they may have been created via
    kanban CLI which doesn't set tenant. Both tenant=? AND tenant IS NULL
    are counted when tenant is given.
    """
    import sqlite3
    counts = {"todo": 0, "running": 0, "blocked": 0, "done": 0}
    try:
        db_path = os.environ.get("HERMES_KANBAN_DB", str(Path.home() / ".hermes" / "kanban.db"))
        conn = sqlite3.connect(db_path)
        try:
            if tenant:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS n FROM tasks "
                    "WHERE status != 'archived' AND (tenant = ? OR tenant IS NULL) "
                    "GROUP BY status",
                    (tenant,),
                )
            else:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS n FROM tasks WHERE status != 'archived' GROUP BY status"
                )
            for r in rows:
                s = r[0]
                if s in counts:
                    counts[s] = r[1]
        finally:
            conn.close()
    except Exception:
        pass
    return counts


@router.get("/projects")
def list_projects_api():
    """List all Agora projects with cron status and task counts."""
    try:
        from project_planner import list_projects, get_cron_status
        projects = list_projects()
        for proj in projects:
            proj_name = proj.get("name", "")
            if proj_name:
                cron_status = get_cron_status(proj_name)
                proj["cron_status"] = cron_status
                sched = cron_status.get("schedule", "")
                if sched and sched.startswith("every ") and sched.endswith("m"):
                    try:
                        proj["heartbeat_minutes"] = int(sched[6:-1])
                    except (ValueError, IndexError):
                        pass
                proj["task_counts"] = _count_tasks(tenant=proj.get("board") or f"agora-{proj_name}")
        return {"projects": projects}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/projects/{name}")
def get_project_api(name: str):
    """Get project detail with cron status and task counts."""
    try:
        from project_planner import get_project, get_cron_status
        proj = get_project(name)
        if proj is None:
            raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
        cron_status = get_cron_status(name)
        proj["cron_status"] = cron_status
        # Sync heartbeat_minutes with the actual cron schedule so the
        # dashboard always shows the real interval (users may change it
        # via `hermes cron edit` or the WebUI cron manager).
        sched = cron_status.get("schedule", "")
        if sched and sched.startswith("every ") and sched.endswith("m"):
            try:
                proj["heartbeat_minutes"] = int(sched[6:-1])
            except (ValueError, IndexError):
                pass
        proj["task_counts"] = _count_tasks(tenant=proj.get("board") or f"agora-{name}")
        return proj
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/projects")
def start_project_api(req: StartProjectRequest):
    """Start a new self-driving project."""
    try:
        from project_planner import start_project
        result = start_project(
            project_name=req.name,
            workdir=req.workdir,
            goal=req.goal,
            description=req.description,
            stop_condition=req.stop_condition,
            max_rounds=req.max_rounds,
            team=req.team,
            heartbeat_member=req.heartbeat_member,
            heartbeat_minutes=req.heartbeat_minutes,
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/projects/{name}/stop")
def stop_project_api(name: str):
    """Stop a project (pause heartbeat, mark as stopped)."""
    try:
        from project_planner import stop_project
        result = stop_project(name)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/projects/{name}")
def delete_project_api(name: str):
    """Permanently delete a project."""
    try:
        from project_planner import delete_project
        result = delete_project(name)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/projects/{name}/heartbeat")
def update_project_heartbeat(name: str, req: UpdateHeartbeatRequest):
    """Update the heartbeat interval for a project."""
    try:
        from project_planner import update_heartbeat
        result = update_heartbeat(name, req.minutes)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/projects/{name}/pause")
def pause_project_heartbeat(name: str):
    """Pause a project's heartbeat cron job."""
    try:
        from project_planner import pause_heartbeat
        result = pause_heartbeat(name)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/projects/{name}/resume")
def resume_project_heartbeat(name: str):
    """Resume a project's heartbeat cron job."""
    try:
        from project_planner import resume_heartbeat
        result = resume_heartbeat(name)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/projects/{name}/trigger")
def trigger_project_heartbeat(name: str):
    """Manually trigger a project heartbeat right now."""
    try:
        from project_planner import trigger_heartbeat
        result = trigger_heartbeat(name)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/projects/{name}/tasks")
def get_project_tasks_api(name: str):
    """Get kanban tasks for a project.

    Tasks are stored on the default kanban board.  We query by
    board slug (``agora-{project_name}``) and fall back to listing
    all non-archived tasks on the default board when the project's
    board doesn't exist yet (tasks created before board isolation
    was implemented have no board/tenant set).
    """
    try:
        import sqlite3
        from project_planner import get_project

        proj = get_project(name)
        if proj is None:
            raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

        board = proj.get("board", f"agora-{name}")

        # Try the kanban board API first
        try:
            import sys
            sys.path.insert(0, "/usr/local/lib/hermes-agent")
            from hermes_cli import kanban_db
            boards = kanban_db.list_boards()
            board_slugs = [b["slug"] for b in boards]
        except Exception:
            board_slugs = ["default"]

        db_path = os.environ.get("HERMES_KANBAN_DB", str(Path.home() / ".hermes" / "kanban.db"))
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            # List non-archived tasks for this project's board (or NULL tenant
            # for tasks created via kanban CLI before board isolation).
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status != 'archived' "
                "AND (tenant = ? OR tenant IS NULL) "
                "ORDER BY priority DESC, created_at ASC",
                (board,),
            ).fetchall()
            tasks = []
            counts = {"todo": 0, "running": 0, "blocked": 0, "done": 0}
            for r in rows:
                t = dict(r)
                status = t.get("status", "todo")
                if status in counts:
                    counts[status] += 1
                tasks.append({
                    "id": t.get("id"),
                    "title": t.get("title"),
                    "status": status,
                    "assignee": t.get("assignee"),
                    "priority": t.get("priority", 0),
                    "created_at": t.get("created_at"),
                    "started_at": t.get("started_at"),
                    "completed_at": t.get("completed_at"),
                })
            return {"tasks": tasks, "task_counts": counts}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# AI-generated SOUL.md
# --------------------------------------------------------------------------- #




# ---------------------------------------------------------------------------
# Human discussion participation
# --------------------------------------------------------------------------- #

class AddMessageRequest(BaseModel):
    role: str = Field("user", description="Message role")
    content: str = Field(..., description="Message content")


@router.post("/motions/{motion_id}/messages")
def add_motion_message(motion_id: str, req: AddMessageRequest):
    """Add a human message to a discussion (human participation)."""
    try:
        from agora.storage import motions as db
        motion = db.get_motion(motion_id)
        if motion is None:
            raise HTTPException(status_code=404, detail="Motion not found")
        if motion["status"] == "closed":
            raise HTTPException(status_code=400, detail="Motion is closed")

        db.add_message(
            motion_id=motion_id,
            role=req.role,
            round_num=motion.get("step_count", 0),
            stance="neutral",
            content=req.content,
            step_type="human_input",
        )
        return {"status": "added", "motion_id": motion_id, "role": req.role}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
