"""
IronCore V2 — Webhook API Routes
===================================
Phase 4 — The Architect (Gemini 3.1)

Exposes:
  POST   /webhooks/{suffix}            — Inbound webhook receiver (no auth — verified by HMAC)
  GET    /api/webhooks                 — List all registrations        [admin]
  POST   /api/webhooks                 — Create registration            [admin]
  DELETE /api/webhooks/{id}            — Remove registration            [admin]
  GET    /api/webhooks/{id}            — Get registration detail        [admin]
  GET    /api/webhooks/{id}/events     — Event history                  [admin]
  POST   /api/webhooks/{id}/test       — Send a test event              [admin]
  POST   /api/webhooks/{id}/enable     — Enable registration            [admin]
  POST   /api/webhooks/{id}/disable    — Disable registration           [admin]

Author: The Architect (IronCore V2) — Gemini 3.1
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ironcore.webhooks.models import WebhookRegistration, WebhookSource
from ironcore.webhooks.server import (
    WebhookNotFoundError,
    WebhookRateLimitExceeded,
    WebhookReplayError,
    WebhookServer,
    WebhookSignatureError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _get_webhook_server(request: Request) -> WebhookServer:
    server: Optional[WebhookServer] = getattr(request.app.state, "webhook_server", None)
    if server is None:
        raise HTTPException(
            status_code=503,
            detail="Webhook server not initialised. Set IRONCORE_WEBHOOKS_ENABLED=true.",
        )
    return server


def _require_admin(request: Request) -> None:
    """Lightweight admin check using app.state.auth."""
    auth = getattr(request.app.state, "auth", None)
    if auth is None:
        raise HTTPException(status_code=503, detail="Auth service unavailable.")
    api_key = request.headers.get("x-ironcore-api-key", "")
    principal = auth.authenticate(api_key, require_admin=True)
    if principal is None:
        raise HTTPException(status_code=403, detail="Admin API key required.")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


# ─── Request / response models ────────────────────────────────────────────────


class CreateWebhookRequest(BaseModel):
    name: str = Field(..., description="Human-readable label for this webhook.")
    source: WebhookSource
    endpoint_suffix: str = Field(
        ...,
        pattern=r"^[a-z0-9\-_]{3,80}$",
        description="URL-safe suffix: POST /webhooks/{endpoint_suffix}",
    )
    target_actions: List[str] = Field(
        default_factory=list,
        description="IronCore action names to trigger on each received event.",
    )
    verify_signature: bool = True


class WebhookRegistrationResponse(BaseModel):
    id: str
    name: str
    source: str
    endpoint_suffix: str
    endpoint_url: str
    target_actions: List[str]
    enabled: bool
    verify_signature: bool
    # Secret exposed only on creation — never in list/get responses
    secret: Optional[str] = None


def _reg_to_response(
    reg: WebhookRegistration, base_url: str, include_secret: bool = False
) -> WebhookRegistrationResponse:
    return WebhookRegistrationResponse(
        id=reg.id,
        name=reg.name,
        source=reg.source.value,
        endpoint_suffix=reg.endpoint_suffix,
        endpoint_url=f"{base_url.rstrip('/')}/webhooks/{reg.endpoint_suffix}",
        target_actions=reg.target_actions,
        enabled=reg.enabled,
        verify_signature=reg.verify_signature,
        secret=reg.secret if include_secret else None,
    )


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


# ─── Inbound webhook receiver ─────────────────────────────────────────────────


@router.post("/webhooks/{suffix}", status_code=202)
async def receive_webhook(
    suffix: str,
    request: Request,
) -> Dict[str, Any]:
    """
    Inbound webhook endpoint.  No auth required — the sender's HMAC signature
    acts as authentication.  Returns 202 Accepted immediately; actual
    processing happens in a background asyncio task.
    """
    server = _get_webhook_server(request)

    # Resolve registration by URL suffix
    reg = server.get_registration_by_suffix(suffix)
    if reg is None or not reg.enabled:
        # Return 404 — don't reveal the difference between "disabled" and "unknown"
        raise HTTPException(status_code=404, detail="Webhook endpoint not found.")

    raw_body = await request.body()
    # Lower-case all header names for consistent lookup
    headers = {k.lower(): v for k, v in request.headers.items()}
    ip = _client_ip(request)

    try:
        result = await server.handle_webhook(
            registration_id=reg.id,
            raw_body=raw_body,
            headers=headers,
            client_ip=ip,
        )
    except WebhookRateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except WebhookSignatureError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except WebhookReplayError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except WebhookNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return result


# ─── Management routes (admin only) ──────────────────────────────────────────


@router.get("/api/webhooks", response_model=List[WebhookRegistrationResponse])
async def list_webhooks(request: Request) -> List[WebhookRegistrationResponse]:
    """Return all webhook registrations.  Secrets are not included."""
    _require_admin(request)
    server = _get_webhook_server(request)
    base = _base_url(request)
    return [_reg_to_response(r, base, include_secret=False) for r in server.list_registrations()]


@router.post("/api/webhooks", response_model=WebhookRegistrationResponse, status_code=201)
async def create_webhook(
    body: CreateWebhookRequest,
    request: Request,
) -> WebhookRegistrationResponse:
    """
    Register a new webhook endpoint.
    The generated ``secret`` is returned **only once** in this response.
    Store it safely — it will not be shown again.
    """
    _require_admin(request)
    server = _get_webhook_server(request)
    reg = WebhookRegistration(
        name=body.name,
        source=body.source,
        endpoint_suffix=body.endpoint_suffix,
        target_actions=body.target_actions,
        verify_signature=body.verify_signature,
    )
    try:
        server.register(reg)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    logger.info("[WebhookRoutes] Created registration id=%s suffix=%s", reg.id, reg.endpoint_suffix)
    return _reg_to_response(reg, _base_url(request), include_secret=True)


@router.get("/api/webhooks/{registration_id}", response_model=WebhookRegistrationResponse)
async def get_webhook(registration_id: str, request: Request) -> WebhookRegistrationResponse:
    """Return a single webhook registration detail.  Secret is not included."""
    _require_admin(request)
    server = _get_webhook_server(request)
    reg = server.get_registration(registration_id)
    if reg is None:
        raise HTTPException(status_code=404, detail="Registration not found.")
    return _reg_to_response(reg, _base_url(request), include_secret=False)


@router.delete("/api/webhooks/{registration_id}", status_code=204)
async def delete_webhook(registration_id: str, request: Request) -> None:
    """Delete a webhook registration permanently."""
    _require_admin(request)
    server = _get_webhook_server(request)
    if server.get_registration(registration_id) is None:
        raise HTTPException(status_code=404, detail="Registration not found.")
    server.unregister(registration_id)
    logger.info("[WebhookRoutes] Deleted registration id=%s", registration_id)


@router.get("/api/webhooks/{registration_id}/events")
async def get_webhook_events(registration_id: str, request: Request) -> List[Dict[str, Any]]:
    """Return the recent event history for a registration (last 1 000 events)."""
    _require_admin(request)
    server = _get_webhook_server(request)
    if server.get_registration(registration_id) is None:
        raise HTTPException(status_code=404, detail="Registration not found.")
    events = server.get_event_history(registration_id)
    return [e.model_dump() for e in events]


@router.post("/api/webhooks/{registration_id}/test", status_code=202)
async def test_webhook(registration_id: str, request: Request) -> Dict[str, Any]:
    """
    Inject a synthetic test event for the registration.
    Useful for verifying that target_actions are configured correctly.
    Signature verification is skipped for test events.
    """
    _require_admin(request)
    server = _get_webhook_server(request)
    reg = server.get_registration(registration_id)
    if reg is None:
        raise HTTPException(status_code=404, detail="Registration not found.")

    import json as _json
    test_body = _json.dumps({"test": True, "source": reg.source.value}).encode()
    # Temporarily disable signature check for the test call
    original_verify = reg.verify_signature
    reg.verify_signature = False
    try:
        result = await server.handle_webhook(
            registration_id=registration_id,
            raw_body=test_body,
            headers={"x-webhook-test": "true"},
            client_ip="test-client",
        )
    finally:
        reg.verify_signature = original_verify

    return {**result, "note": "Test event injected. Check event history."}


@router.post("/api/webhooks/{registration_id}/enable", status_code=200)
async def enable_webhook(registration_id: str, request: Request) -> Dict[str, str]:
    """Enable a previously disabled registration."""
    _require_admin(request)
    server = _get_webhook_server(request)
    reg = server.get_registration(registration_id)
    if reg is None:
        raise HTTPException(status_code=404, detail="Registration not found.")
    reg.enabled = True
    return {"status": "enabled", "id": registration_id}


@router.post("/api/webhooks/{registration_id}/disable", status_code=200)
async def disable_webhook(registration_id: str, request: Request) -> Dict[str, str]:
    """Disable a registration without deleting it."""
    _require_admin(request)
    server = _get_webhook_server(request)
    reg = server.get_registration(registration_id)
    if reg is None:
        raise HTTPException(status_code=404, detail="Registration not found.")
    reg.enabled = False
    return {"status": "disabled", "id": registration_id}
