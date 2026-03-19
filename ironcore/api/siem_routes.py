"""
SIEM API Routes — Phase 5, Security V3.

Endpoints consumed by ChatGPT UI V3 (SIEM Dashboard panel):

  GET  /api/enterprise/siem/stream    → SSE live SIEMEvent stream
  GET  /api/enterprise/siem/events    → paginated events (in-memory ring buffer)
  GET  /api/enterprise/siem/stats     → aggregated stats by severity/event_type
  GET  /api/enterprise/siem/config    → current transport config
  POST /api/enterprise/siem/test      → emit a test event and verify transport

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from ironcore.api.enterprise_auth import require_enterprise, EnterprisePrincipal
from ironcore.config import cfg

logger = logging.getLogger(__name__)

router = APIRouter(tags=["SIEM"])

# Module-level singleton. Injected at server startup via set_siem_streamer().
_streamer = None

# In-memory event log for /events endpoint (last N events in ring buffer)
# We keep a separate deque since SIEMStreamer buffer is write-only (drains on flush)
import collections as _coll
_event_log: _coll.deque = _coll.deque(maxlen=10_000)


def set_siem_streamer(streamer: Any) -> None:
    """Called at startup to inject the shared SIEMStreamer instance."""
    global _streamer
    _streamer = streamer
    logger.info("[SIEMRoutes] SIEMStreamer registered.")


def record_event(event: Dict[str, Any]) -> None:
    """
    Called by other modules (Firewall, Guardrail) to add an event to the log.
    Non-blocking — just appends to the deque.
    """
    entry = {
        "event_id": event.get("event_id", str(time.time())),
        "event_type": event.get("event_type", "unknown"),
        "severity": event.get("severity", "low"),
        "session_id": event.get("session_id", ""),
        "agent": event.get("agent", "ironcore"),
        "timestamp": event.get("timestamp", time.time()),
        "payload": event.get("payload", {}),
        "seq": len(_event_log),
    }
    _event_log.append(entry)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/stream")
async def siem_event_stream(
    interval: float = Query(3.0, ge=1.0, le=30.0),
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> StreamingResponse:
    """
    GET /api/enterprise/siem/stream?interval=3

    Server-Sent Events: push new SIEM events every N seconds.
    Only events not yet sent to this client are pushed (cursor tracking).
    """
    async def _stream():
        cursor = len(_event_log)
        while True:
            current = len(_event_log)
            if current > cursor:
                new_events = list(_event_log)[cursor:current]
                for ev in new_events:
                    yield f"data: {json.dumps({'type': 'siem_event', 'data': ev})}\n\n"
                cursor = current
            await asyncio.sleep(interval)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/events")
async def list_siem_events(
    severity: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> Dict[str, Any]:
    """
    GET /api/enterprise/siem/events?severity=high&limit=50

    Return paginated SIEM events, newest first.
    Supports filter by severity (low|medium|high|critical) and event_type.
    """
    events = list(_event_log)
    # Reverse so newest first
    events = list(reversed(events))
    if severity:
        events = [e for e in events if e.get("severity") == severity]
    if event_type:
        events = [e for e in events if e.get("event_type") == event_type]

    total = len(events)
    page = events[offset : offset + limit]

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "events": page,
    }


@router.get("/stats")
async def siem_stats(
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> Dict[str, Any]:
    """
    GET /api/enterprise/siem/stats

    Aggregated stats: counts by severity, by event_type, top sessions.
    """
    events = list(_event_log)
    severity_counts: Dict[str, int] = {}
    type_counts: Dict[str, int] = {}
    session_counts: Dict[str, int] = {}

    for ev in events:
        sev = ev.get("severity", "unknown")
        etype = ev.get("event_type", "unknown")
        sess = ev.get("session_id", "")

        severity_counts[sev] = severity_counts.get(sev, 0) + 1
        type_counts[etype] = type_counts.get(etype, 0) + 1
        if sess:
            session_counts[sess] = session_counts.get(sess, 0) + 1

    top_sessions = sorted(session_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    buffer_stats: Dict[str, Any] = {}
    if _streamer is not None:
        buffer_stats = {
            "overflow_count": getattr(_streamer, "overflow_count", 0),
            "sent_count": getattr(_streamer, "sent_count", 0),
            "failed_count": getattr(_streamer, "failed_count", 0),
            "buffer_len": getattr(_streamer, "buffer_len", 0),
        }

    return {
        "total_events": len(events),
        "severity_counts": severity_counts,
        "event_type_counts": type_counts,
        "top_sessions_by_event_count": [
            {"session_id": sid, "event_count": cnt} for sid, cnt in top_sessions
        ],
        "transport_buffer": buffer_stats,
    }


@router.get("/config")
async def siem_config(
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> Dict[str, Any]:
    """
    GET /api/enterprise/siem/config

    Return current SIEM configuration (transport names, buffer settings, hostname).
    No secrets are exposed.
    """
    return {
        "enabled": True,
        "transports": cfg.siem_transports,
        "buffer_size": cfg.siem_buffer_size,
        "flush_interval_seconds": cfg.siem_flush_interval,
        "hostname": cfg.siem_hostname,
        "failsafe_path": cfg.siem_failsafe_path,
    }


class TestEventRequest(BaseModel):
    event_type: str = "action_executed"
    severity: str = "low"
    session_id: str = "test-session"
    message: str = "Manual test event from admin"


@router.post("/test")
async def siem_test_event(
    body: TestEventRequest,
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> Dict[str, Any]:
    """
    POST /api/enterprise/siem/test

    Emit a test event into the ring buffer (and to transport if available).
    Used by admin to verify the SIEM pipeline is working.
    """
    now = time.time()
    ev: Dict[str, Any] = {
        "event_id": f"test-{int(now)}",
        "event_type": body.event_type,
        "severity": body.severity,
        "session_id": body.session_id,
        "agent": "ironcore-admin-test",
        "timestamp": now,
        "payload": {"message": body.message, "source": "admin_test_endpoint"},
    }
    record_event(ev)

    transport_result = "no_transport_configured"
    if _streamer is not None:
        try:
            from ironcore.monitoring.schemas import AuditLogEntry  # type: ignore
            entry = AuditLogEntry(
                session_id=body.session_id,
                agent="ironcore-admin",
                event_type=body.event_type,
                timestamp=now,
                seq=0,
                payload={"message": body.message},
            )
            await _streamer.emit(entry)
            transport_result = "emitted_to_transport"
        except Exception as exc:  # noqa: BLE001
            transport_result = f"transport_error: {exc}"

    return {
        "status": "ok",
        "event_id": ev["event_id"],
        "timestamp": now,
        "transport_result": transport_result,
        "ring_buffer_size": len(_event_log),
    }
