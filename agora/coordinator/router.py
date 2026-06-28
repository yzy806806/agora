"""HTTP REST API routes for the Agora Coordinator service.

Provides endpoints for agent management, motion CRUD, and result queries.
Phase 9.3: Updated /agents/register + admin approve/reject/suspend endpoints.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response

from .config import settings
from .models import (
    AgentInfo,
    AgentRegisterRequest,
    AgentRegistrationResponse,
    AgentStatus,
    AssessmentResponse,
    Motion,
    MotionCreateRequest,
    MotionHistoryResponse,
    MotionListResponse,
    MotionResultResponse,
    MotionStatus,
    RegistrationStatusResponse,
    VotingMethod,
)
from .task_models import TaskNode
from .dashboard_models import (
    ExecutionSlotItem,
    ExecutionSlotsResponse,
    TaskCreateRequest,
    TaskDetailResponse,
    TaskGraphCreateRequest,
    TaskGraphDetailResponse,
    TaskGraphItem,
    TaskGraphListResponse,
    TaskItem,
    TaskListResponse,
    TaskResultResponse,
)
from .rbac import Permission, Role, get_current_role, requires
from .registration_rate_limiter import RegistrationRateLimiter
from .state import InvalidTransitionError, StateMachine
from .storage import Storage

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level singletons — set by main.py during app startup
_storage: Optional[Storage] = None
_state_machine: Optional[StateMachine] = None
_reg_rate_limiter: Optional[RegistrationRateLimiter] = None


def init_deps(storage: Storage, state_machine: StateMachine) -> None:
    """Initialize module dependencies. Called once at app startup."""
    global _storage, _state_machine, _reg_rate_limiter
    _storage = storage
    _state_machine = state_machine
    _reg_rate_limiter = RegistrationRateLimiter()


def _get_storage() -> Storage:
    if _storage is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return _storage


def _get_sm() -> StateMachine:
    if _state_machine is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return _state_machine


def _require_admin(authorization: str = Header("")) -> None:
    """Raise 401 if admin token not set or doesn't match."""
    admin_token = settings.admin_token
    if not admin_token:
        raise HTTPException(status_code=501, detail="Admin token not configured")
    token = authorization.removeprefix("Bearer ").strip()
    if token != admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Agent API
# ---------------------------------------------------------------------------


@router.post("/agents/register", response_model=AgentRegistrationResponse,
             status_code=201)
async def register_agent(
    request: AgentRegisterRequest,
    http_request: Request,
) -> AgentRegistrationResponse:
    """Self-register a new agent (Phase 15.C: no auth required).

    IP-based rate limiting: 3 requests/minute per IP.
    If AGORA_REQUIRE_APPROVAL=true (default): agent is PENDING,
    returns registration_token for polling approval status.
    If AGORA_REQUIRE_APPROVAL=false: auto-approved, returns agent_token.
    """
    # Phase 15.C.5: IP-based rate limiting
    client_ip = http_request.client.host if http_request.client else "unknown"
    if _reg_rate_limiter and not _reg_rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many registration requests. Try again later.",
        )

    storage = _get_storage()
    existing = await storage.get_agent(request.agent_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Agent already registered")

    agent_token = f"ag-{secrets.token_hex(16)}"
    require_approval = settings.require_approval
    is_approved = not require_approval
    approval_status = "approved" if is_approved else "pending"
    # Phase 15.C: generate registration_token for pending agents
    reg_token = secrets.token_hex(16) if require_approval else None

    await storage.register_agent(
        agent_id=request.agent_id,
        name=request.name,
        model=request.model,
        capabilities=request.capabilities,
        role="participant",
        agent_type=request.agent_type.value,
        max_concurrent_tasks=request.max_concurrent_tasks,
        agent_token=agent_token,
        is_approved=is_approved,
        approval_status=approval_status,
        registration_token=reg_token or "",
    )

    message = (
        "Registration successful. You can now connect via WebSocket."
        if is_approved
        else "Registration pending approval. Use registration_token to poll status."
    )

    return AgentRegistrationResponse(
        agent_id=request.agent_id,
        status=AgentStatus(approval_status),
        agent_token=agent_token if is_approved else None,
        registration_token=reg_token,
        message=message,
        approval_required=require_approval,
    )


@router.get("/agents/register/{agent_id}/status",
            response_model=RegistrationStatusResponse)
async def get_registration_status(
    agent_id: str,
    registration_token: str = Header(alias="X-Registration-Token"),
) -> RegistrationStatusResponse:
    """Poll agent registration approval status (Phase 15.C.2).

    Requires X-Registration-Token header matching the token
    returned during registration.
    """
    storage = _get_storage()
    agent = await storage.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Verify registration_token matches
    stored_token = agent.get("registration_token", "")
    if not stored_token or stored_token != registration_token:
        raise HTTPException(
            status_code=403,
            detail="Invalid or expired registration token",
        )

    approval_status = agent.get("approval_status", "pending")
    agent_token = agent.get("agent_token") if approval_status == "approved" else None

    # Phase 15.C fix: one-time read — clear registration_token
    # after agent successfully retrieves agent_token.
    if approval_status == "approved":
        await storage.clear_registration_token(agent_id)

    messages = {
        "pending": "Registration is pending admin approval.",
        "approved": "Registration approved. You can now connect via WebSocket.",
        "rejected": "Registration was rejected by an admin.",
    }

    return RegistrationStatusResponse(
        agent_id=agent_id,
        approval_status=approval_status,
        agent_token=agent_token,
        message=messages.get(approval_status, "Unknown status."),
    )


@router.delete("/agents/{agent_id}")
@requires(Permission.ADMIN_FULL)
async def deregister_agent(
    agent_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Deregister an agent from the system."""
    storage = _get_storage()
    agent = await storage.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    await storage.deregister_agent(agent_id)
    return {"status": "ok"}


@router.get("/agents", response_model=list[AgentInfo])
@requires(Permission.CONFIG_READ)
async def list_agents(
    _rbac_role: Role | None = Depends(get_current_role),
) -> list[AgentInfo]:
    """List all registered agents."""
    storage = _get_storage()
    agents = await storage.list_agents()
    return [AgentInfo(**a) for a in agents]


# ---------------------------------------------------------------------------
# Admin API (Phase 9.3)
# ---------------------------------------------------------------------------


@router.get("/admin/agents", response_model=list[AgentInfo])
@requires(Permission.ADMIN_FULL)
async def admin_list_agents(
    authorization: str = Header(""),
    _rbac_role: Role | None = Depends(get_current_role),
) -> list[AgentInfo]:
    """List all agents including approval status. Admin only."""
    _require_admin(authorization)
    storage = _get_storage()
    agents = await storage.list_agents()
    return [AgentInfo(**a) for a in agents]


@router.post("/admin/agents/{agent_id}/approve")
@requires(Permission.AGENT_APPROVE)
async def admin_approve_agent(
    agent_id: str,
    authorization: str = Header(""),
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Approve a pending agent. Admin only."""
    _require_admin(authorization)
    storage = _get_storage()
    agent = await storage.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    await storage.set_agent_approval(agent_id, True, "approved")
    return {"agent_id": agent_id, "status": "approved"}


@router.post("/admin/agents/{agent_id}/reject")
@requires(Permission.ADMIN_FULL)
async def admin_reject_agent(
    agent_id: str,
    authorization: str = Header(""),
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Reject a pending agent. Admin only."""
    _require_admin(authorization)
    storage = _get_storage()
    agent = await storage.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    await storage.set_agent_approval(agent_id, False, "rejected")
    return {"agent_id": agent_id, "status": "rejected"}


@router.post("/admin/agents/{agent_id}/suspend")
@requires(Permission.ADMIN_FULL)
async def admin_suspend_agent(
    agent_id: str,
    authorization: str = Header(""),
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Suspend a previously approved agent. Admin only."""
    _require_admin(authorization)
    storage = _get_storage()
    agent = await storage.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    await storage.set_agent_approval(agent_id, False, "suspended")
    return {"agent_id": agent_id, "status": "suspended"}


# ---------------------------------------------------------------------------
# Motion API
# ---------------------------------------------------------------------------


@router.post("/motions", response_model=Motion)
@requires(Permission.DISCUSSION_CREATE)
async def create_motion(
    request: MotionCreateRequest,
    _rbac_role: Role | None = Depends(get_current_role),
) -> Motion:
    """Create a new motion (topic for discussion)."""
    storage = _get_storage()
    data = await storage.create_motion(
        title=request.title,
        description=request.description,
        rounds=request.rounds,
        voting_method=request.voting_method.value,
        context=request.context or "",
    )
    return Motion(**data)


@router.get("/motions", response_model=MotionListResponse)
@requires(Permission.CONFIG_READ)
async def list_motions(
    status: Optional[MotionStatus] = None,
    limit: int = 100,
    offset: int = 0,
    _rbac_role: Role | None = Depends(get_current_role),
) -> MotionListResponse:
    """List motions, optionally filtered by status."""
    storage = _get_storage()
    motions_data = await storage.list_motions(
        status=status.value if status else None,
        limit=limit,
        offset=offset,
    )
    motions = [Motion(**m) for m in motions_data]
    return MotionListResponse(
        motions=motions, total=len(motions), limit=limit, offset=offset
    )


@router.get("/motions/{motion_id}", response_model=Motion)
@requires(Permission.CONFIG_READ)
async def get_motion(
    motion_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> Motion:
    """Get details of a specific motion."""
    storage = _get_storage()
    data = await storage.get_motion(motion_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Motion not found")
    return Motion(**data)


@router.post("/motions/{motion_id}/start")
@requires(Permission.DISCUSSION_CREATE)
async def start_motion(
    motion_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Start discussion on a draft motion."""
    sm = _get_sm()
    storage = _get_storage()
    try:
        new_status = await sm.transition(motion_id, "start")
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    motion = await storage.get_motion(motion_id)
    # Phase 11.5a: Push to dashboard event bus
    from .event_bus import publish
    await publish("MOTION_STATUS", {
        "motion_id": motion_id, "status": new_status.value,
    }, channel="discussions")
    return {"status": "started", "current_status": new_status.value}


# ---------------------------------------------------------------------------
# History / Result API
# ---------------------------------------------------------------------------


@router.get("/motions/{motion_id}/history", response_model=MotionHistoryResponse)
@requires(Permission.CONFIG_READ)
async def get_history(
    motion_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> MotionHistoryResponse:
    """Get discussion history (messages + votes) for a motion."""
    storage = _get_storage()
    motion = await storage.get_motion(motion_id)
    if motion is None:
        raise HTTPException(status_code=404, detail="Motion not found")
    messages = await storage.get_messages(motion_id)
    votes = await storage.get_votes(motion_id)
    return MotionHistoryResponse(messages=messages, votes=votes)


@router.get("/motions/{motion_id}/result", response_model=MotionResultResponse)
@requires(Permission.CONFIG_READ)
async def get_result(
    motion_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> MotionResultResponse:
    """Get the final result of a closed motion."""
    storage = _get_storage()
    motion = await storage.get_motion(motion_id)
    if motion is None:
        raise HTTPException(status_code=404, detail="Motion not found")
    if motion["status"] != MotionStatus.CLOSED:
        raise HTTPException(status_code=400, detail="Motion not closed yet")

    vote_summary = await storage.get_vote_summary(motion_id)
    decision = motion.get("decision", "no_consensus")
    rationale = motion.get("rationale", "")
    action_items = motion.get("action_items", [])

    return MotionResultResponse(
        motion_id=motion_id,
        decision=decision,
        votes=vote_summary.get("counts", {}),
        rationale=rationale,
        action_items=action_items,
    )


# ---------------------------------------------------------------------------
# Phase 2: Smart Discussion & Advanced Voting API
# ---------------------------------------------------------------------------


@router.get("/motions/{motion_id}/assessment",
            response_model=AssessmentResponse)
@requires(Permission.CONFIG_READ)
async def get_assessment(
    motion_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> AssessmentResponse:
    """Get the latest assessment for a motion's discussion."""
    storage = _get_storage()
    motion = await storage.get_motion(motion_id)
    if motion is None:
        raise HTTPException(status_code=404, detail="Motion not found")

    assessment = await storage.get_latest_assessment(motion_id)
    if assessment is None:
        raise HTTPException(
            status_code=404, detail="No assessment found")

    return AssessmentResponse(
        motion_id=motion_id,
        result=assessment.get("result", ""),
        consensus_level=assessment.get("consensus_level", ""),
        metrics=assessment.get("metrics", {}),
        rationale=assessment.get("rationale", ""),
        recommendations=assessment.get("recommendations", []),
    )


@router.post("/motions/{motion_id}/force-vote")
@requires(Permission.DISCUSSION_VOTE)
async def force_vote(
    motion_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> dict:
    """Force a motion into voting phase regardless of round progress."""
    sm = _get_sm()
    storage = _get_storage()
    motion = await storage.get_motion(motion_id)
    if motion is None:
        raise HTTPException(status_code=404, detail="Motion not found")
    if motion["status"] not in ("discussing", "assessing", "devils_advocate"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot force vote from status {motion['status']}")

    try:
        new_status = await sm.transition(motion_id, "start_voting")
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return {"status": "voting_started", "current_status": new_status.value}


# ---------------------------------------------------------------------------
# Phase 11.1a: Task Query API (Dashboard)
# ---------------------------------------------------------------------------


@router.post("/tasks", response_model=TaskDetailResponse, status_code=201)
@requires(Permission.DISCUSSION_CREATE)
async def create_task_api(
    request: TaskCreateRequest,
    _rbac_role: Role | None = Depends(get_current_role),
) -> TaskDetailResponse:
    """Manually create a task from Dashboard.

    If graph_id is omitted, a default graph is auto-created.
    If assigned_to is set, the task starts in 'assigned' status.
    """
    storage = _get_storage()
    graph_id = request.graph_id
    motion_id = ""

    # Auto-create a graph if none specified
    if not graph_id:
        graph_id = f"graph-{uuid.uuid4().hex[:12]}"
        motion_id = f"manual-{uuid.uuid4().hex[:8]}"
        await storage.create_task_graph(
            graph_id=graph_id, motion_id=motion_id,
        )
    else:
        # Fetch existing graph to get motion_id
        graph = await storage.get_task_graph(graph_id)
        if graph is None:
            raise HTTPException(
                status_code=404, detail=f"Task graph {graph_id} not found")
        motion_id = graph.get("motion_id", "")

    task_id = f"task-{uuid.uuid4().hex[:12]}"
    status = "assigned" if request.assigned_to else "pending"
    task = TaskNode(
        id=task_id,
        graph_id=graph_id,
        motion_id=motion_id,
        title=request.title,
        description=request.description,
        status=status,
        assigned_to=request.assigned_to,
        required_capabilities=request.required_capabilities,
        depends_on=request.depends_on,
    )
    result = await storage.create_task(task)
    # Publish event for dashboard WS
    from .event_bus import publish
    await publish("TASK_UPDATE", {
        "task_id": task_id, "status": status,
        "graph_id": graph_id,
    }, channel="tasks")
    return TaskDetailResponse(**result)


@router.post("/task-graphs", response_model=TaskGraphDetailResponse,
             status_code=201)
@requires(Permission.DISCUSSION_CREATE)
async def create_task_graph_api(
    request: TaskGraphCreateRequest,
    _rbac_role: Role | None = Depends(get_current_role),
) -> TaskGraphDetailResponse:
    """Manually create a task graph from Dashboard."""
    storage = _get_storage()
    graph_id = request.id or f"graph-{uuid.uuid4().hex[:12]}"
    motion_id = request.motion_id or f"manual-{uuid.uuid4().hex[:8]}"
    result = await storage.create_task_graph(
        graph_id=graph_id, motion_id=motion_id,
        parallel_mode=request.parallel_mode,
        max_parallel_slots=request.max_parallel_slots,
        resource_conflict_policy=request.resource_conflict_policy,
    )
    return TaskGraphDetailResponse(
        id=result["id"], motion_id=result["motion_id"],
        parallel_mode=result.get("parallel_mode", "auto"),
        max_parallel_slots=result.get("max_parallel_slots", 10),
        resource_conflict_policy=result.get(
            "resource_conflict_policy", "warn"),
        created_at=result.get("created_at"),
        tasks=[],
    )


@router.get("/tasks", response_model=TaskListResponse)
@requires(Permission.CONFIG_READ)
async def list_tasks_api(
    graph_id: Optional[str] = None,
    status: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    _rbac_role: Role | None = Depends(get_current_role),
) -> TaskListResponse:
    """List tasks with optional filters."""
    storage = _get_storage()
    tasks = await storage.list_tasks(
        graph_id=graph_id, status=status,
        agent_id=agent_id, limit=limit, offset=offset,
    )
    items = [TaskItem(**t) for t in tasks]
    return TaskListResponse(
        tasks=items, total=len(items), limit=limit, offset=offset)


@router.get("/tasks/{task_id}", response_model=TaskDetailResponse)
@requires(Permission.CONFIG_READ)
async def get_task_detail(
    task_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> TaskDetailResponse:
    """Get single task detail."""
    storage = _get_storage()
    task = await storage.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskDetailResponse(**task)


@router.get("/tasks/{task_id}/result", response_model=TaskResultResponse)
@requires(Permission.CONFIG_READ)
async def get_task_result_api(
    task_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> TaskResultResponse:
    """Get structured task result (Protocol v2)."""
    storage = _get_storage()
    task = await storage.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    result = await storage.get_task_result(task_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail="No structured result for this task")
    return TaskResultResponse(**result)


@router.get("/task-graphs", response_model=TaskGraphListResponse)
@requires(Permission.CONFIG_READ)
async def list_task_graphs_api(
    limit: int = 100,
    offset: int = 0,
    _rbac_role: Role | None = Depends(get_current_role),
) -> TaskGraphListResponse:
    """List all task graphs."""
    storage = _get_storage()
    graphs = await storage.list_task_graphs(limit=limit, offset=offset)
    items = [TaskGraphItem(**g) for g in graphs]
    return TaskGraphListResponse(
        graphs=items, total=len(items), limit=limit, offset=offset)


@router.get("/task-graphs/{graph_id}",
            response_model=TaskGraphDetailResponse)
@requires(Permission.CONFIG_READ)
async def get_task_graph_detail(
    graph_id: str,
    _rbac_role: Role | None = Depends(get_current_role),
) -> TaskGraphDetailResponse:
    """Get graph with all tasks."""
    storage = _get_storage()
    graph = await storage.get_task_graph(graph_id)
    if graph is None:
        raise HTTPException(
            status_code=404, detail="Task graph not found")
    tasks = [TaskDetailResponse(**t) for t in graph.get("tasks", [])]
    return TaskGraphDetailResponse(
        id=graph["id"], motion_id=graph["motion_id"],
        parallel_mode=graph.get("parallel_mode", "auto"),
        max_parallel_slots=graph.get("max_parallel_slots", 10),
        resource_conflict_policy=graph.get(
            "resource_conflict_policy", "warn"),
        created_at=graph.get("created_at"),
        tasks=tasks)


@router.get("/execution-slots", response_model=ExecutionSlotsResponse)
@requires(Permission.CONFIG_READ)
async def get_execution_slots_api(
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
    _rbac_role: Role | None = Depends(get_current_role),
) -> ExecutionSlotsResponse:
    """Current execution slot status."""
    storage = _get_storage()
    slots = await storage.get_execution_slots(
        agent_id=agent_id, status=status)
    items = [ExecutionSlotItem(**s) for s in slots]
    return ExecutionSlotsResponse(slots=items, total=len(items))
