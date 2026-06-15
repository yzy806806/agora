"""Pydantic data models for the Agora Coordinator service.

Defines all request/response models, enums, and WebSocket message types.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MessageType(str, Enum):
    """WebSocket message types."""

    REGISTER = "REGISTER"
    DEREGISTER = "DEREGISTER"
    NEW_MOTION = "NEW_MOTION"
    REQUEST_SPEAK = "REQUEST_SPEAK"
    SPEAK = "SPEAK"
    SPEECH_ADDED = "SPEECH_ADDED"
    BROADCAST = "BROADCAST"
    ROUND_COMPLETE = "ROUND_COMPLETE"
    REQUEST_VOTE = "REQUEST_VOTE"
    VOTE = "VOTE"
    VOTE_CONFIRMED = "VOTE_CONFIRMED"
    RESULT = "RESULT"
    ERROR = "ERROR"
    PING = "PING"
    PONG = "PONG"
    WELCOME = "WELCOME"
    AGENT_OFFLINE = "AGENT_OFFLINE"
    # Phase 2: smart discussion
    ASSESSMENT = "ASSESSMENT"
    TOPIC_REDIRECT = "TOPIC_REDIRECT"
    DEVILS_ADVOCATE_REQUEST = "DEVILS_ADVOCATE_REQUEST"
    DEVILS_ADVOCATE_RESPONSE = "DEVILS_ADVOCATE_RESPONSE"
    # Phase 9: task execution
    TASK_ASSIGNED = "TASK_ASSIGNED"
    TASK_STATUS = "TASK_STATUS"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_VERIFY = "TASK_VERIFY"
    TASK_ACCEPT_RESULT = "TASK_ACCEPT_RESULT"
    HEARTBEAT = "HEARTBEAT"  # Phase 9.3: periodic agent heartbeat
    # Phase 9.4: rate limiting
    RATE_LIMIT_WARNING = "RATE_LIMIT_WARNING"
    RATE_LIMITED = "RATE_LIMITED"
    RATE_LIMIT_RESET = "RATE_LIMIT_RESET"
    RATE_LIMIT_REPORT = "RATE_LIMIT_REPORT"  # agent → coordinator
    # Phase 10: parallel execution
    TASK_STARTED = "TASK_STARTED"         # agent→coordinator: execution begun
    TASK_BLOCKED = "TASK_BLOCKED"         # coordinator→agent: resource conflict
    TASK_UNBLOCKED = "TASK_UNBLOCKED"     # coordinator→agent: resource available
    TASK_RETRY = "TASK_RETRY"             # coordinator→agent: re-execute failed task
    TASK_PROGRESS = "TASK_PROGRESS"       # agent→coordinator: progress update
    GRAPH_COMPLETE = "GRAPH_COMPLETE"     # coordinator→all: graph finished
    GRAPH_ABORTED = "GRAPH_ABORTED"       # coordinator→all: graph aborted
    # Phase 13: pipeline messages (coordinator→dashboard)
    PIPELINE_PHASE_CHANGE = "PIPELINE_PHASE_CHANGE"
    PIPELINE_TASK_UPDATE = "PIPELINE_TASK_UPDATE"
    PIPELINE_COMPLETED = "PIPELINE_COMPLETED"
    PIPELINE_ERROR = "PIPELINE_ERROR"
    # Phase 14: workspace messages (coordinator→agents)
    WORKSPACE_FILE_CHANGED = "WORKSPACE_FILE_CHANGED"
    WORKSPACE_LOCK_ACQUIRED = "WORKSPACE_LOCK_ACQUIRED"
    WORKSPACE_LOCK_RELEASED = "WORKSPACE_LOCK_RELEASED"
    WORKSPACE_LOCK_EXPIRED = "WORKSPACE_LOCK_EXPIRED"


class MotionStatus(str, Enum):
    """Motion lifecycle states."""

    DRAFT = "draft"
    DISCUSSING = "discussing"
    ASSESSING = "assessing"
    DEVILS_ADVOCATE = "devils_advocate"
    VOTING = "voting"
    CLOSED = "closed"


class VotingMethod(str, Enum):
    """Supported voting methods."""

    SIMPLE_MAJORITY = "simple_majority"
    SUPERMAJORITY = "supermajority"
    UNANIMOUS = "unanimous"
    WEIGHTED = "weighted"
    # Phase 2: advanced voting
    BORDA_COUNT = "borda_count"
    RANKED_CHOICE = "ranked_choice"
    APPROVAL = "approval"
    RANGE = "range"
    INSTANT_RUNOFF = "instant_runoff"

class Stance(str, Enum):
    """Agent stance on a motion."""

    SUPPORT = "support"
    OPPOSE = "oppose"
    NEUTRAL = "neutral"


class VoteChoice(str, Enum):
    """Vote options."""

    YES = "yes"
    NO = "no"
    ABSTAIN = "abstain"


class AgentRole(str, Enum):
    """Agent roles in discussions."""

    COORDINATOR = "coordinator"
    PARTICIPANT = "participant"
    EXPERT = "expert"
    DEVIL_ADVOCATE = "devil_advocate"
    OBSERVER = "observer"


class AgentType(str, Enum):
    """How the agent connects to Agora (Phase 9.3)."""
    HERMES = "hermes"
    DOCKER = "docker"
    CLI = "cli"
    CUSTOM = "custom"


class AgentStatus(str, Enum):
    """Approval + online state combined (Phase 9.3)."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class DiscussionRole(str, Enum):
    """Discussion roles for multi-model diversity (Phase 6.5)."""

    SUPPORT_ADVOCATE = "support_advocate"
    OPPOSE_ADVOCATE = "oppose_advocate"
    EXPERT = "expert"
    NEUTRAL = "neutral"
    FACT_CHECKER = "fact_checker"
    CREATIVE = "creative"


class Decision(str, Enum):
    """Final decision outcomes."""

    ADOPTED = "adopted"
    REJECTED = "rejected"
    NO_CONSENSUS = "no_consensus"


# ---------------------------------------------------------------------------
# WebSocket Message
# ---------------------------------------------------------------------------


class WSMessage(BaseModel):
    """Generic WebSocket message envelope."""

    type: MessageType
    motion_id: Optional[str] = None
    agent_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent Models
# ---------------------------------------------------------------------------


class AgentRegisterRequest(BaseModel):
    """Request body for agent registration (Phase 9.3)."""

    agent_id: str
    name: str
    capabilities: list[str] = Field(default_factory=list)

    # New fields (Phase 9.3)
    agent_type: AgentType = AgentType.HERMES
    model: str = "unknown"
    max_concurrent_tasks: int = 2
    auth_token: str = ""  # Agent's own API key for re-auth


class AgentInfo(BaseModel):
    """Agent information stored in the system."""

    agent_id: str
    name: str
    model: str = ""

    # Phase 9.3 new fields
    agent_type: AgentType = AgentType.HERMES
    max_concurrent_tasks: int = 2
    agent_token: str = ""
    is_approved: bool = False
    approval_status: AgentStatus = AgentStatus.PENDING

    capabilities: list[str] = Field(default_factory=list)
    role: AgentRole = AgentRole.PARTICIPANT
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_online: bool = False
    last_seen: Optional[datetime] = None
    load: float = 0.0
    active_tasks: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    """Per-agent runtime configuration, sent in WELCOME payload."""

    max_concurrent_tasks: int = 2
    heartbeat_interval_seconds: int = 30
    heartbeat_timeout_seconds: int = 120
    tpm_limit: int = 10000
    tpm_burst_factor: float = 1.5  # Phase 9.4: burst multiplier (1.0-3.0)
    allowed_discussion_roles: list[str] = Field(
        default_factory=lambda: ["participant"]
    )
    auto_accept_tasks: bool = False


class AgentRegistrationResponse(BaseModel):
    """Response for POST /api/v1/agents/register."""

    agent_id: str
    status: AgentStatus
    agent_token: str
    message: str = ""


# ---------------------------------------------------------------------------
# Motion Models
# ---------------------------------------------------------------------------


class MotionCreateRequest(BaseModel):
    """Request body for creating a motion."""

    title: str
    description: str
    context: Optional[str] = None
    rounds: int = 3
    voting_method: VotingMethod = VotingMethod.SIMPLE_MAJORITY
    # Phase 2: advanced voting options
    voting_options: Optional[list[str]] = None
    voting_config: Optional[dict[str, Any]] = None


class Motion(BaseModel):
    """A discussion motion/topic."""

    id: str
    title: str
    description: str
    context: Optional[str] = None
    rounds: int = 3
    voting_method: VotingMethod = VotingMethod.SIMPLE_MAJORITY
    status: MotionStatus = MotionStatus.DRAFT
    current_round: int = 0
    decision: Optional[Decision] = None
    rationale: Optional[str] = None
    action_items: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None

    # Phase 2: smart discussion fields
    smart_mode: bool = True
    assessment_config: Optional[dict[str, Any]] = None
    devils_advocate_count: int = 0
    focus_areas: list[str] = Field(default_factory=list)
    early_vote_triggered: bool = False


# ---------------------------------------------------------------------------
# Speak & Vote Models
# ---------------------------------------------------------------------------


class SpeakRequest(BaseModel):
    """Request body for submitting a speech."""

    motion_id: str
    round: int
    stance: Stance
    content: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class VoteRequest(BaseModel):
    """Request body for casting a vote."""

    motion_id: str
    vote: VoteChoice
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: Optional[str] = None


# Phase 2: advanced vote request models

class MultipleChoiceVoteRequest(BaseModel):
    """Request body for multiple-choice voting."""

    motion_id: str
    type: str = "multiple_choice"
    vote: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: Optional[str] = None


class RankingVoteRequest(BaseModel):
    """Request body for ranked-choice voting."""

    motion_id: str
    type: str = "ranking"
    ranking: list[str]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ApprovalVoteRequest(BaseModel):
    """Request body for approval voting."""

    motion_id: str
    type: str = "approval"
    approved: list[str]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class RangeVoteRequest(BaseModel):
    """Request body for range/score voting."""

    motion_id: str
    type: str = "range"
    scores: dict[str, float]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------


class MotionListResponse(BaseModel):
    """Paginated motion list response."""

    motions: list[Motion]
    total: int
    limit: int
    offset: int


class MotionHistoryResponse(BaseModel):
    """Discussion history for a motion."""

    messages: list[dict[str, Any]]
    votes: list[dict[str, Any]]


class MotionResultResponse(BaseModel):
    """Final result of a motion discussion."""

    motion_id: str
    decision: Decision
    votes: dict[str, int]
    rationale: str
    action_items: list[str]


class ErrorResponse(BaseModel):
    """Standard error response."""

    type: str = "ERROR"
    code: str
    message: str
    details: Optional[dict[str, Any]] = None


class AssessmentResponse(BaseModel):
    """Response body for motion assessment."""

    motion_id: str
    result: str
    consensus_level: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    recommendations: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 8: Dashboard / Event models
# ---------------------------------------------------------------------------


class EventResponse(BaseModel):
    """A single event from the event log."""

    event_id: int
    type: str
    detail: str = ""
    motion_id: Optional[str] = None
    agent_id: Optional[str] = None
    created_at: str = ""


class TimelineEntry(BaseModel):
    """A single entry in a discussion timeline."""

    time: str
    type: str
    agent_id: Optional[str] = None
    content: str = ""
    round_num: Optional[int] = None


# ---------------------------------------------------------------------------
# Phase 11.1b: Agent Config & Token Rotation Models
# ---------------------------------------------------------------------------


class AgentConfigUpdate(BaseModel):
    """Request body for PUT /admin/agents/{agent_id}/config."""

    tpm_limit: Optional[int] = Field(None, ge=1)
    tpm_burst_factor: Optional[float] = Field(None, ge=1.0, le=3.0)
    max_concurrent_tasks: Optional[int] = Field(None, ge=1, le=100)
    role: Optional[str] = None
    allowed_discussion_roles: Optional[list[str]] = None


class AgentConfigResponse(BaseModel):
    """Response for PUT /admin/agents/{agent_id}/config."""

    agent_id: str
    tpm_limit: int
    tpm_burst_factor: float
    max_concurrent_tasks: int
    role: str
    allowed_discussion_roles: list[str] = Field(default_factory=list)


class TokenRotateResponse(BaseModel):
    """Response for POST /admin/agents/{agent_id}/token."""

    agent_id: str
    agent_token: str


# ---------------------------------------------------------------------------
# Phase 12.5: Session Persistence Models
# ---------------------------------------------------------------------------


class SessionCreateRequest(BaseModel):
    """Request body for POST /api/v1/sessions."""

    agent_id: str
    project_id: str = "default"
    session_type: str = "task_execution"
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    input_messages: list[dict[str, Any]] = Field(default_factory=list)
    output_messages: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    outcome: str = "success"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionRecord(BaseModel):
    """A single session record returned by the API."""

    id: str
    agent_id: str
    project_id: str = "default"
    session_type: str = "task_execution"
    started_at: str
    ended_at: Optional[str] = None
    input_messages: list[dict[str, Any]] = Field(default_factory=list)
    output_messages: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    outcome: str = "success"
    metadata: dict[str, Any] = Field(default_factory=dict)
    notes: list[dict[str, Any]] = Field(default_factory=list)


class SessionListResponse(BaseModel):
    """Paginated session list response."""

    sessions: list[SessionRecord]
    total: int
    limit: int
    offset: int


class SessionNoteRequest(BaseModel):
    """Request body for POST /api/v1/sessions/{id}/notes."""

    author: str
    content: str
    tags: list[str] = Field(default_factory=list)
