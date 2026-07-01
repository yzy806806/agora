"""Agora dashboard plugin — backend API routes.

Mounted at /api/plugins/agora/ by the Hermes dashboard plugin system.

Provides REST endpoints for:
  - Profile management (list, create, delete, config, SOUL, skills, toolsets)
  - Motion management (list, show, result, discuss)
"""
from __future__ import annotations

import json
import logging
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
# Profile management
# ---------------------------------------------------------------------------

class CreateProfileRequest(BaseModel):
    name: str = Field(..., description="Profile name (lowercase, hyphens)")
    clone_from: Optional[str] = Field(None, description="Source profile to clone")
    clone_config: bool = Field(True, description="Copy config.yaml, .env, SOUL.md, skills")
    description: Optional[str] = Field(None, description="Free-form description")
    preset: Optional[str] = Field(None, description="Preset role: architect/developer/reviewer")

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


@router.post("/profiles")
def create_profile(req: CreateProfileRequest):
    """Create a new Hermes profile, optionally from a preset."""
    try:
        profiles_mod = _get_profiles_module()
        profile_dir = profiles_mod.create_profile(
            name=req.name,
            clone_from=req.clone_from,
            clone_config=req.clone_config,
            description=req.description,
        )

        # Apply preset: write role-specific SOUL.md and config
        if req.preset:
            _apply_preset(profile_dir, req.preset)

        return {
            "name": req.name,
            "path": str(profile_dir),
            "preset": req.preset,
            "message": f"Profile '{req.name}' created"
                       + (f" with {req.preset} preset" if req.preset else ""),
        }
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("create_profile failed: %s", exc)
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
    """List skills available to a profile."""
    try:
        profiles_mod = _get_profiles_module()
        profile_dir = profiles_mod.get_profile_dir(name)
        if not profile_dir.exists():
            raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

        skills_dir = profile_dir / "skills"
        skills = []
        if skills_dir.is_dir():
            for sf in sorted(skills_dir.rglob("SKILL.md")):
                skill_dir = sf.parent
                rel = str(skill_dir.relative_to(skills_dir))
                skills.append({
                    "name": rel,
                    "path": str(sf),
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
            "messages": [
                {
                    "id": m["id"],
                    "role": m["role"],
                    "round": m["round_num"],
                    "stance": m["stance"],
                    "content": m["content"],
                    "timestamp": m["timestamp"],
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
# Preset logic
# ---------------------------------------------------------------------------

_PRESETS = {
    "architect": {
        "soul": """You are the **Architect** in an Agora deliberation team.

Your role is to provide architectural and design leadership.

Focus areas:
- System architecture and high-level design decisions
- Technology stack selection and trade-offs
- Scalability, maintainability, and extensibility
- Interface contracts and module boundaries
- Risk assessment from an architectural perspective

Be specific and actionable. Reference concrete patterns and principles.
When you disagree, explain your reasoning and propose alternatives.
""",
        "description": "Architecture and design leadership — makes tech stack and system design decisions.",
    },
    "developer": {
        "soul": """You are the **Developer** in an Agora deliberation team.

Your role is to provide implementation expertise and practical feasibility assessment.

Focus areas:
- Implementation details and code structure
- API design and data models
- Feasibility and effort estimation
- Dependency management and integration points
- Build, test, and deployment considerations

Propose concrete approaches with pseudo-code when helpful.
Challenge architectural decisions that are impractical.
""",
        "description": "Implementation expert — writes code, assesses feasibility, handles build/deploy.",
    },
    "reviewer": {
        "soul": """You are the **Reviewer** in an Agora deliberation team.

Your role is to provide quality assurance and critical analysis.

Focus areas:
- Code quality, readability, and maintainability
- Security vulnerabilities and attack surfaces
- Edge cases, failure modes, and error handling
- Testing strategy and coverage requirements
- Performance bottlenecks and resource constraints

Be constructive: identify issues AND suggest remedies.
Prioritize findings by severity.
""",
        "description": "Quality and security reviewer — finds edge cases, tests, and vulnerabilities.",
    },
}


def _apply_preset(profile_dir: Path, preset: str) -> None:
    """Apply a role preset to a profile directory."""
    preset_data = _PRESETS.get(preset)
    if not preset_data:
        return

    # Write SOUL.md
    soul_path = profile_dir / "SOUL.md"
    soul_path.write_text(preset_data["soul"])

    # Update profile.yaml description
    import yaml
    profile_yaml_path = profile_dir / "profile.yaml"
    meta = {}
    if profile_yaml_path.exists():
        with open(profile_yaml_path) as f:
            meta = yaml.safe_load(f) or {}
    meta["description"] = preset_data["description"]
    meta["description_auto"] = False
    with open(profile_yaml_path, "w") as f:
        yaml.dump(meta, f, default_flow_style=False, allow_unicode=True)

    logger.info("Applied preset '%s' to profile at %s", preset, profile_dir)


@router.get("/presets")
def list_presets():
    """List available role presets."""
    return {
        "presets": [
            {"name": k, "description": v["description"]}
            for k, v in _PRESETS.items()
        ]
    }


# ---------------------------------------------------------------------------
# Create Agora team — one-click setup
# ---------------------------------------------------------------------------

class CreateTeamRequest(BaseModel):
    clone_from: str = Field("default", description="Source profile to clone from")
    models: Optional[dict[str, str]] = Field(None, description="Per-role model override, e.g. {architect: deepseekv4pro}")

@router.post("/team")
def create_agora_team(req: CreateTeamRequest):
    """Create a full Agora team (architect + developer + reviewer profiles)."""
    results = []
    for preset_name in _PRESETS:
        try:
            profiles_mod = _get_profiles_module()
            profile_dir = profiles_mod.create_profile(
                name=preset_name,
                clone_from=req.clone_from,
                clone_config=True,
                description=_PRESETS[preset_name]["description"],
            )
            _apply_preset(profile_dir, preset_name)

            # Apply model override if provided
            if req.models and preset_name in req.models:
                config_path = profile_dir / "config.yaml"
                import yaml
                config = {}
                if config_path.exists():
                    with open(config_path) as f:
                        config = yaml.safe_load(f) or {}
                model_cfg = config.get("model", {})
                if not isinstance(model_cfg, dict):
                    model_cfg = {"default": model_cfg} if model_cfg else {}
                model_cfg["default"] = req.models[preset_name]
                config["model"] = model_cfg
                with open(config_path, "w") as f:
                    yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

            results.append({
                "name": preset_name,
                "path": str(profile_dir),
                "model": req.models.get(preset_name) if req.models else None,
                "created": True,
            })
        except FileExistsError:
            results.append({"name": preset_name, "created": False, "error": "already exists"})
        except Exception as exc:
            results.append({"name": preset_name, "created": False, "error": str(exc)})

    return {"team": results, "message": f"Created {sum(1 for r in results if r.get('created'))} profiles"}


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
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from agora.storage import motions as db

        # Auto-resolve participants from team if not specified
        participants = req.participants
        chair = req.chair
        if not participants and req.project:
            try:
                from agora.team_manager import get_team_for_project
                team = get_team_for_project(req.project)
                if team:
                    participants = [w["name"] for w in team.get("workers", [])]
                    if not chair:
                        # Find the leader in the team
                        for w in team.get("workers", []):
                            if w.get("role") == "leader":
                                chair = w["name"]
                                break
            except Exception as exc:
                logger.warning("Team lookup failed: %s", exc)

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
            max_steps=req.max_steps,
        )

        # Spawn the discussion driver as a background process
        # The driver is a Python script that imports DiscussionDriver and runs it
        try:
            import subprocess as _sp
            import os as _os
            hermes_bin = None
            try:
                from agora.utils import find_hermes_binary
                hermes_bin = find_hermes_binary()
            except Exception:
                pass

            # Write a small runner script
            runner_path = Path(_os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "agora" / "run_discussion.py"
            runner_path.parent.mkdir(parents=True, exist_ok=True)
            runner_path.write_text(f'''\
#!/usr/bin/env python3
"""Auto-generated discussion runner."""
import sys
sys.path.insert(0, "{str(Path(__file__).parent.parent)}")
from agora.discussion.driver import DiscussionDriver
driver = DiscussionDriver(
    motion_id="{motion["id"]}",
    chair_profile="{chair}",
    participants={participants!r},
    workdir="{workdir}",
    project_name="{req.project}",
    max_steps={req.max_steps},
)
result = driver.run()
print(f"Discussion result: {{result.decision}} ({{result.steps_completed}} steps)")
''')

            # Spawn it in the background
            log_path = Path(_os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "agora" / f"discussion_{motion['id']}.log"
            log_fd = open(log_path, "a")
            _sp.Popen(
                ["python3", str(runner_path)],
                stdout=log_fd,
                stderr=log_fd,
                start_new_session=True,
                cwd=workdir or None,
            )
            logger.info("Discussion driver spawned for motion %s (log=%s)", motion["id"], log_path)
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


# --------------------------------------------------------------------------- #
#  Leader management                                                          #
# --------------------------------------------------------------------------- #

class CreateLeaderRequest(BaseModel):
    name: str = Field(..., description="Leader profile name")
    project: str = Field(..., description="Project name to manage")
    clone_from: str = Field("coder", description="Source profile to clone")
    heartbeat_minutes: int = Field(15, description="Heartbeat interval in minutes")
    model: Optional[str] = Field(None, description="Override model")


@router.get("/leaders")
def list_leaders():
    """List all registered team leaders with cron status."""
    try:
        import sys, json as _json
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from agora.leader_manager import list_leaders as _list
        leaders = _list()
        cron_jobs_path = Path.home() / ".hermes" / "profiles" / "coder" / "cron" / "jobs.json"
        cron_map = {}
        try:
            if cron_jobs_path.exists():
                cron_data = _json.loads(cron_jobs_path.read_text())
                for job in cron_data.get("jobs", []):
                    cron_map[job.get("name", "")] = job
        except Exception:
            pass
        for leader in leaders:
            cron_name = "heartbeat-" + leader.get("name", "")
            job = cron_map.get(cron_name)
            leader["cron_enabled"] = job.get("enabled", False) if job else False
            leader["cron_next_run"] = job.get("next_run_at") if job else None
            leader["cron_last_run"] = job.get("last_run_at") if job else None
            leader["cron_schedule"] = job.get("schedule_display") if job else None
        return {"leaders": leaders}
    except Exception as exc:
        logger.error("list_leaders failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/leaders")
def create_leader(req: CreateLeaderRequest):
    """Create a team leader. Automatically creates a cron job for heartbeat."""
    try:
        from agora.leader_manager import create_leader as _create
        result = _create(
            name=req.name, project=req.project, clone_from=req.clone_from,
            heartbeat_minutes=req.heartbeat_minutes, model=req.model,
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("create_leader failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/leaders/{name}")
def remove_leader(name: str):
    """Remove a leader and its cron job."""
    try:
        from agora.leader_manager import remove_leader as _remove
        result = _remove(name)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class UpdateHeartbeatRequest(BaseModel):
    minutes: int = Field(..., description="New heartbeat interval in minutes")

@router.put("/leaders/{name}/heartbeat")
def update_heartbeat(name: str, req: UpdateHeartbeatRequest):
    """Update the heartbeat interval for a leader."""
    try:
        from agora.leader_manager import update_heartbeat_schedule
        result = update_heartbeat_schedule(name, req.minutes)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/leaders/{name}/heartbeat/trigger")
def trigger_heartbeat(name: str):
    """Manually trigger a leader heartbeat right now."""
    try:
        from agora.leader_loop import heartbeat
        result = heartbeat(leader_name=name)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/leaders/{name}/pause")
def pause_leader(name: str):
    """Pause a leader's heartbeat cron job."""
    try:
        import subprocess
        result = subprocess.run(
            ["hermes", "cron", "pause", "heartbeat-" + name],
            capture_output=True, text=True, timeout=10,
        )
        return {"name": name, "paused": result.returncode == 0,
                "output": result.stdout.strip()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/leaders/{name}/resume")
def resume_leader(name: str):
    """Resume a leader's heartbeat cron job."""
    try:
        import subprocess
        result = subprocess.run(
            ["hermes", "cron", "resume", "heartbeat-" + name],
            capture_output=True, text=True, timeout=10,
        )
        return {"name": name, "resumed": result.returncode == 0,
                "output": result.stdout.strip()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# --------------------------------------------------------------------------- #
#  Worker management                                                          #
# --------------------------------------------------------------------------- #

class CreateWorkerRequest(BaseModel):
    name: str = Field(..., description="Worker profile name")
    role: str = Field(..., description="Role: architect/developer/reviewer/tester/devops")
    clone_from: str = Field("coder")
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


# --------------------------------------------------------------------------- #
#  Team management                                                            #
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


# --------------------------------------------------------------------------- #
#  Project management                                                          #
# --------------------------------------------------------------------------- #

class StartProjectRequest(BaseModel):
    name: str = Field(..., description="Project name")
    goal: str = Field(..., description="Project goal")
    workdir: str = Field("/root", description="Working directory")
    team: Optional[str] = Field(None, description="Team name")
    leader: Optional[str] = Field(None, description="Leader name")
    profile: str = Field("coder", description="Hermes profile for workers")
    max_rounds: int = Field(10, description="Max planning rounds")


@router.get("/projects")
def list_projects_api():
    """List all Agora projects."""
    try:
        from project_planner import list_projects
        return {"projects": list_projects()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/projects/{name}")
def get_project_api(name: str):
    """Get project detail."""
    try:
        from project_planner import get_project
        proj = get_project(name)
        if proj is None:
            raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
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
            profile=req.profile,
            max_rounds=req.max_rounds,
            team=req.team,
        )
        if req.leader:
            import json
            from agora.leader_manager import get_leader, _leader_file
            leader = get_leader(req.leader)
            if leader:
                leader["project"] = req.name
                _leader_file(req.leader).write_text(json.dumps(leader, indent=2))
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/projects/{name}")
def stop_project_api(name: str):
    """Stop a project."""
    try:
        from project_planner import stop_project
        result = stop_project(name)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# --------------------------------------------------------------------------- #
#  AI-generated SOUL.md                                                        #
# --------------------------------------------------------------------------- #

class GenerateSoulRequest(BaseModel):
    name: str = Field(..., description="Worker profile name")
    description: str = Field(..., description="Natural-language role description")
    clone_from: str = Field("coder")
    model: Optional[str] = Field(None)
    toolsets: Optional[list[str]] = Field(None)


@router.post("/workers/generate-soul")
def generate_soul_api(req: GenerateSoulRequest):
    """Generate a custom SOUL.md using LLM, then create the worker profile."""
    try:
        import sys, subprocess, os
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from agora.worker_templates import generate_soul_prompt

        prompt = generate_soul_prompt(req.name, req.description)

        hermes_bin = None
        for c in [
            os.environ.get("HERMES_BIN", ""),
            "/home/ubuntu/.hermes/hermes-agent/venv/bin/hermes",
            "/root/.hermes/hermes-agent/venv/bin/hermes",
            "/usr/local/bin/hermes",
        ]:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                hermes_bin = c
                break
        if not hermes_bin:
            import shutil
            hermes_bin = shutil.which("hermes") or "hermes"

        profile = req.clone_from or "coder"
        result = subprocess.run(
            [hermes_bin, "-p", profile, "chat", "-q", prompt],
            capture_output=True, text=True, timeout=120,
        )

        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"LLM call failed: {result.stderr[:200]}",
            )

        soul_content = result.stdout.strip()
        if not soul_content or len(soul_content) < 50:
            raise HTTPException(status_code=500, detail="LLM returned empty response")

        if "# " in soul_content:
            soul_content = soul_content[soul_content.index("# "):]

        from agora.worker_manager import create_worker
        worker_result = create_worker(
            name=req.name,
            role="custom",
            clone_from=req.clone_from,
            model=req.model,
        )

        if "error" in worker_result:
            raise HTTPException(status_code=400, detail=worker_result["error"])

        from agora.worker_manager import _profiles_root
        profiles_root = _profiles_root()
        soul_path = profiles_root / req.name / "SOUL.md"
        soul_path.write_text(soul_content)

        if req.toolsets:
            import yaml
            config_path = profiles_root / req.name / "config.yaml"
            if config_path.exists():
                cfg = yaml.safe_load(config_path.read_text()) or {}
                cfg["toolsets"] = req.toolsets
                config_path.write_text(yaml.dump(cfg, default_flow_style=False, allow_unicode=True))

        return {
            "status": "created",
            "name": req.name,
            "soul_preview": soul_content[:500],
            "worker": worker_result.get("worker", {}),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# --------------------------------------------------------------------------- #
#  Human discussion participation                                              #
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
