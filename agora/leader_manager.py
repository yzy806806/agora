"""Leader manager — DEPRECATED shim.

All leader functionality has been merged into:
  - worker_manager.py (profile creation, registry)
  - project_planner.py (heartbeat config, cron, session)
  - leader_loop.py (heartbeat execution)

This module exists only for backward compatibility with code that
imports from agora.leader_manager. New code should import from the
correct modules directly.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def create_leader(name, project, clone_from="coder", heartbeat_minutes=15, model=None):
    """DEPRECATED — use worker_manager.create_worker + project_planner.start_project."""
    from .worker_manager import create_worker
    from project_planner import start_project

    # Create the worker profile using leader template
    result = create_worker(name=name, role="leader", clone_from=clone_from, model=model)
    if "error" in result:
        return result

    # Start project with this leader as heartbeat member
    # Note: caller should use start_project directly with heartbeat_member
    logger.warning("create_leader is deprecated. Use create_worker(role='leader') + start_project(heartbeat_member=...) instead.")
    return result


def remove_leader(name, delete_profile=True):
    """DEPRECATED — use worker_manager.remove_worker."""
    from .worker_manager import remove_worker
    return remove_worker(name, delete_profile=delete_profile)


def get_leader(name):
    """DEPRECATED — use worker_manager.get_worker."""
    from .worker_manager import get_worker
    return get_worker(name)


def list_leaders():
    """DEPRECATED — use worker_manager.list_workers and filter is_leader."""
    from .worker_manager import list_workers
    return [w for w in list_workers() if w.get("is_leader")]


def get_leader_for_project(project):
    """DEPRECATED — use project_planner.get_heartbeat_member."""
    from project_planner import get_heartbeat_member
    member = get_heartbeat_member(project)
    if member:
        from .worker_manager import get_worker
        return get_worker(member)
    return None


def bind_leader_to_project(name, project):
    """DEPRECATED — use project_planner.start_project with heartbeat_member."""
    logger.warning("bind_leader_to_project is deprecated. Use start_project(heartbeat_member=...) instead.")
    return {"error": "Deprecated. Use project_planner.start_project with heartbeat_member parameter."}


def update_heartbeat(name, pid=None):
    """DEPRECATED — use project_planner.update_heartbeat_status."""
    logger.warning("update_heartbeat is deprecated. Use project_planner.update_heartbeat_status instead.")
    # Can't determine project from name alone anymore
    return None


def update_heartbeat_schedule(name, minutes):
    """DEPRECATED — use project_planner.update_heartbeat."""
    logger.warning("update_heartbeat_schedule is deprecated. Use project_planner.update_heartbeat instead.")
    return {"error": "Deprecated. Use project_planner.update_heartbeat(project_name, minutes) instead."}


def _leader_file(name):
    """DEPRECATED — leaders registry no longer exists."""
    from .utils import get_registry_dir, safe_name
    return get_registry_dir("leaders") / f"{safe_name(name)}.json"
