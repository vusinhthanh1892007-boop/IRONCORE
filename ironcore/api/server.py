"""FastAPI application exposing IronCore engine control and observability endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Deque, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ironcore.api.auth import APIKeyAuth, AuthenticatedPrincipal
from ironcore.api.lsp_routes import router as lsp_router
from ironcore.api.ota_routes import router as ota_router
from ironcore.api.scheduler_routes import router as scheduler_router
from ironcore.api.webhook_routes import router as webhook_router
from ironcore.api.channels_routes import router as channels_router, webhook_router as zalo_webhook_router
from ironcore.api.stealth_routes import router as stealth_router
from ironcore.api.firewall_routes import router as firewall_router, set_firewall
from ironcore.api.automation_routes import router as automation_router, set_automation
from ironcore.core.engine import Action, Event, IronCoreEngine
from ironcore.lsp.bridge import LSPBridge
from ironcore.ota.manager import OTAUpdateManager
from ironcore.security.policy_engine import PolicyEngine
from ironcore.security.secrets_vault import SecretsVault

logger = logging.getLogger(__name__)


class AgentRunRequest(BaseModel):
    prompt: str
    max_iterations: int = 10
    system_prompt: str = "You are IronCore, a secure autonomous agent."


class AgentSessionResponse(BaseModel):
    session_id: str
    status: str
    created_at: float
    stopped_at: Optional[float] = None
    history: List[Dict[str, Any]] = Field(default_factory=list)


class ToolTestRequest(BaseModel):
    args: Dict[str, Any] = Field(default_factory=dict)


class SecretStoreRequest(BaseModel):
    name: str
    value: str
    description: str = ""
    ttl_seconds: Optional[float] = None


@dataclass
class AgentSessionRecord:
    session_id: str
    engine: IronCoreEngine
    created_at: float
    status: str = "running"
    stopped_at: Optional[float] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    run_task: Optional[asyncio.Task[List[Dict[str, Any]]]] = None
    event_task: Optional[asyncio.Task[None]] = None
    subscribers: List[asyncio.Queue[Dict[str, Any]]] = field(default_factory=list)


def _build_engine(lsp_bridge: LSPBridge) -> IronCoreEngine:
    engine = IronCoreEngine()
    lsp_bridge.register_tools(engine)
    return engine


def _serialize_event(session_id: str, event: Event) -> Dict[str, Any]:
    payload = event.model_dump(mode="json")
    payload["session_id"] = session_id
    return payload


async def _broadcast_session_event(
    record: AgentSessionRecord,
    audit_log: Deque[Dict[str, Any]],
) -> None:
    """Pump one engine's event bus into audit storage and live subscribers."""
    async for event in record.engine.event_bus.consume_all():
        payload = _serialize_event(record.session_id, event)
        audit_log.append(payload)
        for queue in list(record.subscribers):
            await queue.put(payload)
        if event.event_type == "agent.stopped":
            break


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize shared services and tear them down cleanly."""
    try:
        vault = SecretsVault.from_env()
    except Exception:
        vault = SecretsVault.generate()
        logger.warning("[API] Using ephemeral development vault. Set IRONCORE_VAULT_KEY for persistence.")

    for env_name in (APIKeyAuth.USER_SECRET_NAME, APIKeyAuth.ADMIN_SECRET_NAME):
        env_value = os.environ.get(env_name)
        if env_value and not vault.exists(env_name):
            vault.store(env_name, env_value, description=f"Bootstrapped from env:{env_name}")

    auth = APIKeyAuth(vault=vault)
    policy_engine = PolicyEngine.default()
    lsp_bridge = LSPBridge()
    template_engine = _build_engine(lsp_bridge)

    app.state.vault = vault
    app.state.auth = auth
    app.state.policy_engine = policy_engine
    app.state.lsp_bridge = lsp_bridge
    app.state.template_engine = template_engine
    app.state.sessions = {}
    app.state.audit_log = deque(maxlen=500)

    # ── OTA Update Manager (Phase 2 — The Architect) ───────────────────
    import os as _os
    from pathlib import Path as _Path
    ota_enabled = _os.environ.get("IRONCORE_OTA_ENABLED", "true").lower() != "false"
    if ota_enabled:
        app.state.ota_manager = OTAUpdateManager(
            health_check_url=_os.environ.get(
                "IRONCORE_OTA_HEALTH_URL", "http://localhost:8000/health"
            ),
            health_check_timeout=int(
                _os.environ.get("IRONCORE_OTA_HEALTH_TIMEOUT", "30")
            ),
        )
        logger.info("[API] OTA UpdateManager initialised.")
    else:
        app.state.ota_manager = None
        logger.info("[API] OTA disabled via IRONCORE_OTA_ENABLED=false.")

    # PluginRegistry attached to app state so OTA routes can hot-reload plugins
    app.state.plugin_registry = None  # populated by plugin system when ready

    # ── Cron Scheduler (Phase 3 — The Architect) ────────────────────────
    import os as _os2
    scheduler_enabled = _os2.environ.get("IRONCORE_SCHEDULER_ENABLED", "true").lower() != "false"
    if scheduler_enabled:
        from ironcore.scheduler.cron import CronScheduler
        db_url = _os2.environ.get("IRONCORE_SCHEDULER_DB", "")
        app.state.scheduler = CronScheduler(db_url=db_url)
        await app.state.scheduler.start()
        logger.info("[API] CronScheduler started.")
    else:
        app.state.scheduler = None
        logger.info("[API] Scheduler disabled via IRONCORE_SCHEDULER_ENABLED=false.")

    yield

    # ── Webhook Server (Phase 4 — The Architect) ────────────────────────
    import os as _os3
    webhooks_enabled = _os3.environ.get("IRONCORE_WEBHOOKS_ENABLED", "true").lower() != "false"
    if webhooks_enabled:
        from ironcore.webhooks.server import WebhookServer
        rate_limit = int(_os3.environ.get("IRONCORE_WEBHOOK_RATE_LIMIT", "100"))
        app.state.webhook_server = WebhookServer(rate_limit_per_min=rate_limit)
        logger.info("[API] WebhookServer initialised (rate_limit=%s/min).", rate_limit)
    else:
        app.state.webhook_server = None
        logger.info("[API] Webhooks disabled via IRONCORE_WEBHOOKS_ENABLED=false.")

    yield

    # ── Teardown ────────────────────────────────────────────────────────
    if getattr(app.state, "scheduler", None) is not None:
        await app.state.scheduler.shutdown()
    await lsp_bridge.close()


app = FastAPI(
    title="IronCore API",
    version="0.1.0",
    description="Secure HTTP interface for the IronCore agent system.",
    lifespan=lifespan,
)

app.include_router(ota_router)
app.include_router(scheduler_router)
app.include_router(webhook_router)
app.include_router(lsp_router)  # Phase 7 — LSP Self-Healing routes
app.include_router(channels_router)   # Bot channel management (Telegram, Zalo, Discord, Messenger, WhatsApp)
app.include_router(zalo_webhook_router)  # Webhook receivers: Zalo, Messenger, WhatsApp
app.include_router(stealth_router)    # Stealth browser (Playwright)
app.include_router(firewall_router, prefix="/api/security/firewall")  # Phase 1 V3 — Prompt Firewall
app.include_router(automation_router, prefix="/api/monitoring")         # Phase 6 V3 — Automation & Intelligence

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Phase 14 — CE Tab Throttling ────────────────────────────────────────
_tab_throttle_enabled = os.environ.get("IRONCORE_TAB_THROTTLE_ENABLED", "true").lower() != "false"
if _tab_throttle_enabled:
    from ironcore.middleware.tab_throttle import TabThrottleMiddleware
    _tab_throttle_delay = float(os.environ.get("IRONCORE_TAB_THROTTLE_DELAY", "1.0"))
    app.add_middleware(
        TabThrottleMiddleware,
        delay_seconds=_tab_throttle_delay,
    )
    logger.info("[API] TabThrottleMiddleware registered (delay=%.2fs, CE bypass on EE).", _tab_throttle_delay)


def _require_principal(
    x_ironcore_api_key: Optional[str],
    require_admin: bool = False,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(secret_name="open", is_admin=True)


def require_user(
    x_ironcore_api_key: Optional[str] = Header(default=None, alias="X-IronCore-API-Key"),
) -> AuthenticatedPrincipal:
    return _require_principal(x_ironcore_api_key, require_admin=False)


def require_admin(
    x_ironcore_api_key: Optional[str] = Header(default=None, alias="X-IronCore-API-Key"),
) -> AuthenticatedPrincipal:
    return _require_principal(x_ironcore_api_key, require_admin=True)


def get_engine() -> IronCoreEngine:
    return app.state.template_engine


def get_vault() -> SecretsVault:
    return app.state.vault


def get_policy_engine() -> PolicyEngine:
    return app.state.policy_engine


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Container health check endpoint used by deployment probes."""
    return {
        "status": "ok",
        "service": "ironcore-api",
        "sessions": len(app.state.sessions),
        "tools": len(app.state.template_engine.registered_tools),
    }


@app.post("/v1/agent/run", response_model=AgentSessionResponse)
async def run_agent(
    request: AgentRunRequest,
    _: AuthenticatedPrincipal = Depends(require_user),
) -> AgentSessionResponse:
    session_id = str(uuid.uuid4())
    engine = IronCoreEngine(
        max_iterations=request.max_iterations,
        system_prompt=request.system_prompt,
    )
    app.state.lsp_bridge.register_tools(engine)

    record = AgentSessionRecord(
        session_id=session_id,
        engine=engine,
        created_at=time.time(),
    )
    app.state.sessions[session_id] = record

    record.event_task = asyncio.create_task(
        _broadcast_session_event(record, app.state.audit_log)
    )

    async def _runner() -> List[Dict[str, Any]]:
        try:
            history = await engine.run_loop(request.prompt)
            record.history = history
            record.status = "completed"
            return history
        except asyncio.CancelledError:
            record.status = "cancelled"
            raise
        finally:
            record.stopped_at = time.time()

    record.run_task = asyncio.create_task(_runner())

    return AgentSessionResponse(
        session_id=session_id,
        status=record.status,
        created_at=record.created_at,
        stopped_at=record.stopped_at,
        history=record.history,
    )


@app.get("/v1/agent/sessions/{session_id}", response_model=AgentSessionResponse)
async def get_session(
    session_id: str,
    _: AuthenticatedPrincipal = Depends(require_user),
) -> AgentSessionResponse:
    record = app.state.sessions.get(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if record.run_task is not None and record.run_task.done() and not record.history:
        try:
            record.history = record.run_task.result()
        except Exception:
            record.status = "failed"
    return AgentSessionResponse(
        session_id=record.session_id,
        status=record.status,
        created_at=record.created_at,
        stopped_at=record.stopped_at,
        history=record.history,
    )


@app.post("/v1/agent/sessions/{session_id}/stop")
async def stop_session(
    session_id: str,
    _: AuthenticatedPrincipal = Depends(require_user),
) -> Dict[str, str]:
    record = app.state.sessions.get(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if record.run_task is not None and not record.run_task.done():
        record.run_task.cancel()
        record.status = "cancelling"
    return {"status": record.status}


@app.get("/v1/agent/sessions/{session_id}/stream")
async def stream_session_events(
    session_id: str,
    _: AuthenticatedPrincipal = Depends(require_user),
) -> StreamingResponse:
    record = app.state.sessions.get(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    record.subscribers.append(queue)

    async def _event_stream() -> AsyncGenerator[str, None]:
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event["event_type"] == "agent.stopped":
                    break
        finally:
            if queue in record.subscribers:
                record.subscribers.remove(queue)

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@app.post("/v1/agent/stream")
async def run_agent_stream(
    request: AgentRunRequest,
    _: AuthenticatedPrincipal = Depends(require_user),
) -> StreamingResponse:
    """
    Phase 7 — Real-time token-by-token streaming agent endpoint.
    Returns SSE stream with:  event.data = {"type": "token"|"event"|"done", ...}
    """
    session_id = str(uuid.uuid4())
    engine = IronCoreEngine(
        max_iterations=request.max_iterations,
        system_prompt=request.system_prompt,
    )
    app.state.lsp_bridge.register_tools(engine)

    record = AgentSessionRecord(
        session_id=session_id,
        engine=engine,
        created_at=time.time(),
    )
    app.state.sessions[session_id] = record

    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    record.subscribers.append(queue)

    record.event_task = asyncio.create_task(
        _broadcast_session_event(record, app.state.audit_log)
    )

    async def _runner() -> List[Dict[str, Any]]:
        try:
            history = await engine.run_loop(request.prompt)
            record.history = history
            record.status = "completed"
            return history
        except asyncio.CancelledError:
            record.status = "cancelled"
            raise
        finally:
            record.stopped_at = time.time()

    record.run_task = asyncio.create_task(_runner())

    async def _sse_generator() -> AsyncGenerator[str, None]:
        # Emit session start
        yield f"data: {json.dumps({'type': 'session_start', 'session_id': session_id})}\n\n"
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                except asyncio.TimeoutError:
                    yield "data: {\"type\": \"ping\"}\n\n"
                    continue
                yield f"data: {json.dumps({'type': 'event', **event})}\n\n"
                if event.get("event_type") == "agent.stopped":
                    break
        finally:
            if queue in record.subscribers:
                record.subscribers.remove(queue)
        yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

    return StreamingResponse(
        _sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Session-ID": session_id,
        },
    )


@app.get("/v1/tools")
async def list_tools(
    engine: IronCoreEngine = Depends(get_engine),
    _: AuthenticatedPrincipal = Depends(require_user),
) -> List[Dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "risk_level": tool.risk_level.name,
            "requires_sandbox": tool.requires_sandbox,
            "description": tool.description,
        }
        for tool in engine._tools.values()
    ]


@app.post("/v1/tools/{tool_name}/test")
async def test_tool(
    tool_name: str,
    request: ToolTestRequest,
    engine: IronCoreEngine = Depends(get_engine),
    _: AuthenticatedPrincipal = Depends(require_user),
) -> Dict[str, Any]:
    if tool_name not in engine.registered_tools:
        raise HTTPException(status_code=404, detail="Tool not found.")
    observation = await engine.dispatch(Action(tool_name=tool_name, args=request.args))
    return observation.model_dump(mode="json")


@app.get("/v1/security/policy/status")
async def policy_status(
    policy_engine: PolicyEngine = Depends(get_policy_engine),
    _: AuthenticatedPrincipal = Depends(require_user),
) -> Dict[str, Any]:
    return policy_engine.status()


@app.get("/v1/security/audit/log")
async def audit_log(
    last_n: int = Query(default=50, ge=1, le=500),
    _: AuthenticatedPrincipal = Depends(require_user),
) -> Dict[str, Any]:
    entries = list(app.state.audit_log)[-last_n:]
    return {"entries": entries, "count": len(entries)}


@app.post("/v1/secrets/store")
async def store_secret(
    request: SecretStoreRequest,
    vault: SecretsVault = Depends(get_vault),
    _: AuthenticatedPrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    if vault.exists(request.name):
        vault.update(request.name, request.value, ttl_seconds=request.ttl_seconds)
    else:
        vault.store(
            request.name,
            request.value,
            description=request.description,
            ttl_seconds=request.ttl_seconds,
        )
    return {"stored": request.name}


@app.websocket("/v1/ws/events")
async def websocket_events(
    websocket: WebSocket,
) -> None:
    header_value = websocket.headers.get("x-ironcore-api-key")
    _require_principal(header_value, require_admin=False)
    await websocket.accept()
    event_type = websocket.query_params.get("event_type")
    offset = len(app.state.audit_log)
    try:
        while True:
            while offset < len(app.state.audit_log):
                event = list(app.state.audit_log)[offset]
                offset += 1
                if event_type is None or event["event_type"] == event_type:
                    await websocket.send_json(event)
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        return


