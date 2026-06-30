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
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
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
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
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
    rounds: int = Field(3, description="Max rounds")

@router.post("/motions")
def start_discussion(req: StartDiscussionRequest):
    """Create a motion. The actual discussion runs in agent context only
    (needs ctx.llm), so this just creates the motion record and returns
    instructions for starting it."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from agora.storage import motions as db
        motion = db.create_motion(
            title=req.title,
            description=req.description,
            max_rounds=req.rounds,
            source="user",
        )
        return {
            "motion_id": motion["id"],
            "title": req.title,
            "status": "discussing",
            "message": f"Motion created. Use /agora discuss or agora_raise_motion to start the discussion.",
        }
    except Exception as exc:
        logger.error("start_discussion failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
