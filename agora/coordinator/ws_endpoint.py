"""WebSocket endpoint for the Agora Coordinator service.

Phase 8.2: Added tenant_id parameter for per-tenant isolation.
Phase 9.3: Added token query param for WS auth + approval check.
Phase 10.2d: Added RBAC role check on WS connect.
Routes messages through tenant-specific ConnectionHub.
"""

from __future__ import annotations

import json
import logging

from fastapi import WebSocket

from .input_validation import InputValidator
from .models import MessageType
from .observability.trace import set_trace_id
from .protocol import build_welcome, negotiate_version, parse_version
from .rbac import Permission, Role, check_permission, rbac_enforced
from .rate_limiter import RateLimiter
from .token_rate_limiter import TokenRateLimiter
from .ws import manager
from .ws_handlers import handle_heartbeat, handle_ping, handle_register, handle_speak
from .ws_vote import handle_vote

logger = logging.getLogger(__name__)

_validator = InputValidator()
_rate_limiter = RateLimiter()
_token_limiter = TokenRateLimiter()


async def websocket_endpoint(
    websocket: WebSocket, agent_id: str,
    token: str = "", tenant_id: str = "default",
) -> None:
    """FastAPI WebSocket endpoint at /ws/{agent_id}?token=ag-xxx.

    Phase 8.2: tenant_id query param for multi-tenancy.
    Phase 9.3: token query param for authentication.
    """
    hub = manager.get_hub(tenant_id)
    # Lazy-init deps for non-default tenants
    if hub._storage is None and tenant_id != "default":
        storage_mgr = getattr(websocket.app.state, "storage_mgr", None)
        if storage_mgr is not None:
            from .state import StateMachine
            storage = await storage_mgr.get_tenant_storage(tenant_id)
            sm = StateMachine(storage)
            manager.set_tenant_deps(tenant_id, storage, sm)
            logger.info("Lazy-init deps for tenant %s", tenant_id)

    # Phase 9.3: Token validation BEFORE accepting the connection
    agent = None
    if hub._storage is not None:
        agent = await hub._storage.get_agent(agent_id)
        if token:
            if agent is None:
                await websocket.close(code=4004, reason="Agent not registered")
                return
            stored_token = agent.get("agent_token", "")
            if stored_token and stored_token != token:
                await websocket.close(code=4003, reason="Invalid token")
                return
            if not agent.get("is_approved"):
                await websocket.close(
                    code=4005,
                    reason="Agent not approved. Wait for admin approval.",
                )
                return
        else:
            # No token — reject if agent has a stored token
            if agent is None:
                await websocket.close(code=4004, reason="Agent not registered")
                return
            if agent.get("agent_token"):
                await websocket.close(code=4003, reason="Token required")
                return

    # Phase 10.2d: RBAC role-based access check on WS connect
    if rbac_enforced() and agent is not None:
        agent_role_str = agent.get("role", "agent")
        try:
            role = Role(agent_role_str)
        except ValueError:
            role = Role.AGENT
        if not check_permission(role, Permission.AGENT_REGISTER):
            await websocket.close(code=4003, reason="Insufficient permissions")
            return

    if not await hub.connect(agent_id, websocket):
        return
    try:
        # Phase 14+.E.2: WELCOME with protocol negotiation
        max_concurrent = 2
        if agent:
            max_concurrent = agent.get("max_concurrent_tasks", 2)
        # Phase 9.4: Configure token bucket on connect
        tpm_limit = 10000
        tpm_burst = 1.5
        if agent:
            tpm_limit = agent.get("tpm_limit", 10000)
            tpm_burst = agent.get("tpm_burst_factor", 1.5)
        _token_limiter.configure(agent_id, tpm_limit, tpm_burst)

        # Build WELCOME with protocol version + session info
        from .config import settings as _settings
        welcome = build_welcome(
            agent_id=agent_id,
            tenant_id=tenant_id,
            max_protocol_version=_settings.protocol_version,
        )
        welcome["payload"] = {
            "config": {
                "heartbeat_interval_seconds": 30,
                "heartbeat_timeout_seconds": 120,
                "tpm_limit": tpm_limit,
                "tpm_burst_factor": tpm_burst,
                "max_concurrent_tasks": max_concurrent,
            },
        }
        # v1 compat: agent_id/tenant_id also at top level
        welcome["agent_id"] = agent_id
        welcome["tenant_id"] = tenant_id
        # Store initial version (v1 until agent sends CAPABILITIES)
        hub.set_protocol_version(agent_id, 1.0)
        await hub.send(agent_id, welcome)
        while True:
            data = await websocket.receive_text()
            await _route_message(agent_id, data, hub)
    except Exception:
        pass
    finally:
        hub.disconnect(agent_id)
        await on_agent_disconnect(agent_id, hub)


async def _route_message(agent_id: str, raw: str, hub) -> None:
    """Parse and route a WebSocket message to the appropriate handler."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        await hub.send(agent_id, {
            "type": MessageType.ERROR,
            "payload": {"code": "invalid_json", "message": "Bad JSON"},
        })
        return

    msg_type = msg.get("type", "")
    payload = msg.get("payload", {})
    trace_id = msg.get("trace_id") or ""
    set_trace_id(trace_id)
    storage = hub._storage
    sm = hub._state_machine

    if storage is None or sm is None:
        logger.error("WS deps not initialized")
        return

    if msg_type == MessageType.PING:
        await handle_ping(agent_id, payload, hub)
    elif msg_type == MessageType.REGISTER:
        await handle_register(agent_id, payload, storage, hub)
    elif msg_type == MessageType.SPEAK:
        if not _rate_limiter.check_rate(agent_id, "speak"):
            await hub.send(agent_id, {
                "type": MessageType.ERROR,
                "payload": {"code": "rate_limited", "message": "Speak rate exceeded"},
            })
            return
        try:
            payload = _validator.validate_speak_payload(payload)
        except ValueError as exc:
            await hub.send(agent_id, {
                "type": MessageType.ERROR,
                "payload": {"code": "validation_error", "message": str(exc)},
            })
            return
        await handle_speak(agent_id, payload, storage, sm, hub)
    elif msg_type == MessageType.VOTE:
        if not _rate_limiter.check_rate(agent_id, "vote"):
            await hub.send(agent_id, {
                "type": MessageType.ERROR,
                "payload": {"code": "rate_limited", "message": "Vote rate exceeded"},
            })
            return
        try:
            payload = _validator.validate_vote_payload(payload)
        except ValueError as exc:
            await hub.send(agent_id, {
                "type": MessageType.ERROR,
                "payload": {"code": "validation_error", "message": str(exc)},
            })
            return
        await handle_vote(agent_id, payload, storage, sm, hub)
    elif msg_type == MessageType.DEVILS_ADVOCATE_RESPONSE:
        await _handle_devils_advocate_response(
            agent_id, payload, storage, sm, hub)
    elif msg_type == MessageType.TASK_STATUS:
        from .task_exec import handle_task_status
        parallel_coord = getattr(hub, "_app_state", None)
        if parallel_coord:
            parallel_coord = getattr(parallel_coord, "parallel_coord", None)
        await handle_task_status(
            agent_id, payload, storage, hub, parallel_coord)
    elif msg_type == MessageType.TASK_ACCEPT_RESULT:
        from .task_verify import handle_task_accept_result
        await handle_task_accept_result(agent_id, payload, storage, hub)
    elif msg_type == MessageType.TASK_STARTED:
        from .task_exec import handle_task_started
        parallel_coord = getattr(hub, "_app_state", None)
        if parallel_coord:
            parallel_coord = getattr(parallel_coord, "parallel_coord", None)
        await handle_task_started(
            agent_id, payload, storage, hub, parallel_coord)
    elif msg_type == MessageType.TASK_PROGRESS:
        from .task_exec import handle_task_progress
        await handle_task_progress(agent_id, payload, storage, hub)
    elif msg_type == MessageType.TASK_RESULT:
        from .task_exec import handle_task_result
        parallel_coord = getattr(hub, "_app_state", None)
        if parallel_coord:
            parallel_coord = getattr(parallel_coord, "parallel_coord", None)
        await handle_task_result(
            agent_id, payload, storage, hub, parallel_coord)
    elif msg_type == MessageType.HEARTBEAT:
        await handle_heartbeat(agent_id, payload, storage, hub)
    elif msg_type == MessageType.CAPABILITIES:
        await _handle_capabilities(agent_id, payload, storage, hub)
    elif msg_type == MessageType.NEW_MOTION:
        # NEW_MOTION is coordinator→agent broadcast only (sent via
        # router.py start_motion); agents never send this type.
        logger.debug("Ignoring NEW_MOTION from agent %s", agent_id)
    elif msg_type == MessageType.RATE_LIMIT_REPORT:
        from .ws_rate_limit import check_and_warn
        tokens_used = payload.get("tokens_used", 0)
        _token_limiter.consume(agent_id, tokens_used)
        await check_and_warn(agent_id, hub, _token_limiter)
    elif msg_type == MessageType.TASK_ACK:
        logger.info("Agent %s acknowledged task %s",
                     agent_id, payload.get("task_id", "?"))
    else:
        logger.warning("Unknown type from %s: %s", agent_id, msg_type)


async def _handle_capabilities(
    agent_id: str, payload: dict, storage, hub,
) -> None:
    """Process CAPABILITIES: negotiate protocol version + store info.

    Phase 14+.E.2: v2 agents send this after receiving WELCOME
    to declare their preferred version and structured capabilities.
    v1 agents never send this, so they stay on version 1.0.
    """
    from .config import settings as _settings
    raw_ver = payload.get("protocol_version", 1.0)
    client_ver = parse_version(raw_ver)
    effective = negotiate_version(client_ver, _settings.protocol_version)
    hub.set_protocol_version(agent_id, effective)

    name = payload.get("name", agent_id)
    model = payload.get("model", "unknown")
    caps = payload.get("capabilities", {})
    metadata = payload.get("metadata", {})

    # Update stored agent info if storage available
    if storage is not None:
        await storage.update_agent_capabilities(
            agent_id, caps if isinstance(caps, list) else [caps],
        )
        if model != "unknown":
            await storage.update_agent_model(agent_id, model)

    await hub.send(agent_id, {
        "type": MessageType.WELCOME,
        "agent_id": agent_id,
        "payload": {
            "message": "Capabilities acknowledged",
            "protocol_version": effective,
            "config": {},
        },
    })
    logger.info(
        "Agent %s negotiated protocol v%.1f (requested %.1f)",
        agent_id, effective, client_ver,
    )


async def _handle_devils_advocate_response(
    agent_id: str, payload: dict, storage, sm, hub,
) -> None:
    """Process devil's advocate response and store as a SPEAK message."""
    motion_id = payload.get("motion_id")
    if not motion_id:
        return
    content = payload.get("content", "")
    round_num = payload.get("round", 1)
    await storage.add_message(
        motion_id, agent_id, round_num, "oppose", content,
        [{"source": "devils_advocate"}],
    )
    await hub.broadcast({
        "type": MessageType.BROADCAST,
        "motion_id": motion_id,
        "agent_id": agent_id,
        "payload": {
            "round": round_num,
            "stance": "oppose",
            "content": content,
            "devils_advocate": True,
        },
    })


async def on_agent_disconnect(agent_id: str, hub) -> None:
    """Mark agent offline and notify others in the same tenant."""
    if hub._storage is not None:
        await hub._storage.set_agent_online(agent_id, False)
    _token_limiter.remove(agent_id)
    from .ws_rate_limit import reset_warning_state
    reset_warning_state(agent_id)
    await hub.broadcast({
        "type": MessageType.AGENT_OFFLINE,
        "agent_id": agent_id,
    })
    # Phase 11.5a: Push to dashboard event bus
    from .event_bus import publish
    await publish("AGENT_OFFLINE", {
        "agent_id": agent_id, "reason": "timeout",
    }, channel="events")
    logger.info("Agent %s went offline", agent_id)
