"""
Forensics API Routes — Phase 2, Security V3.

Endpoints consumed by ChatGPT UI V3:

  GET  /api/forensics/sessions                  → list sessions
  GET  /api/forensics/sessions/{id}             → session info + stats
  GET  /api/forensics/sessions/{id}/timeline    → paginated event list
  GET  /api/forensics/sessions/{id}/verify      → run chain verification
  GET  /api/forensics/sessions/{id}/export      → JSON evidence bundle
  GET  /api/forensics/sessions/{id}/export-csv  → CSV flat export
  GET  /api/forensics/sessions/{id}/replay      → SSE replay stream

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from ironcore.enterprise.forensics.exporter import ForensicsExporter
from ironcore.enterprise.forensics.recorder import ForensicsRecorder
from ironcore.enterprise.forensics.replayer import ForensicsReplayer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Forensics"])

# Module-level singletons — inject via set_forensics()
_recorder: Optional[ForensicsRecorder] = None
_replayer: Optional[ForensicsReplayer] = None
_exporter: Optional[ForensicsExporter] = None


def set_forensics(recorder: ForensicsRecorder) -> None:
    """Called at server startup to inject the shared ForensicsRecorder."""
    global _recorder, _replayer, _exporter
    _recorder = recorder
    _replayer = ForensicsReplayer(recorder)
    _exporter = ForensicsExporter(recorder)
    logger.info("[ForensicsRoutes] ForensicsRecorder registered.")


def _get_recorder() -> ForensicsRecorder:
    if _recorder is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Forensics not initialized")
    return _recorder


def _get_replayer() -> ForensicsReplayer:
    if _replayer is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Forensics not initialized")
    return _replayer


def _get_exporter() -> ForensicsExporter:
    if _exporter is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Forensics not initialized")
    return _exporter


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/sessions")
async def list_forensics_sessions(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> List[Dict[str, Any]]:
    """
    GET /api/forensics/sessions

    List forensics-tracked sessions, newest first.
    """
    recorder = _get_recorder()
    sessions = await recorder.list_sessions(limit=limit, offset=offset)
    return [s.model_dump() for s in sessions]


@router.get("/sessions/{session_id}")
async def get_forensics_session(session_id: str) -> Dict[str, Any]:
    """
    GET /api/forensics/sessions/{session_id}

    Return session info + stats summary.
    """
    exporter = _get_exporter()
    stats = await exporter.get_session_stats(session_id)
    if not stats:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Session '{session_id}' not found")
    return stats


@router.get("/sessions/{session_id}/timeline")
async def get_session_timeline(
    session_id: str,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> List[Dict[str, Any]]:
    """
    GET /api/forensics/sessions/{session_id}/timeline

    Return paginated forensics events in sequence order.
    """
    recorder = _get_recorder()
    events = await recorder.get_timeline(session_id, limit=limit, offset=offset)
    if not events and offset == 0:
        info = await recorder.get_session_info(session_id)
        if info is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Session '{session_id}' not found")
    return [
        {
            "seq": e.sequence_number,
            "event_id": e.event_id,
            "event_type": e.event_type.value,
            "timestamp": e.timestamp,
            "metadata": e.metadata,
            "chain_hash_prefix": e.chain_hash[:12],
        }
        for e in events
    ]


@router.get("/sessions/{session_id}/verify")
async def verify_session_chain(session_id: str) -> Dict[str, Any]:
    """
    GET /api/forensics/sessions/{session_id}/verify

    Run HMAC chain verification on the full event log.
    Returns is_valid + any broken link descriptions.
    """
    recorder = _get_recorder()
    info = await recorder.get_session_info(session_id)
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Session '{session_id}' not found")

    is_valid, errors = await recorder.verify_chain(session_id)
    return {
        "session_id": session_id,
        "chain_valid": is_valid,
        "errors": errors,
        "event_count": info.event_count,
        "genesis_hash": info.genesis_hash,
    }


@router.get("/sessions/{session_id}/export")
async def export_session_json(
    session_id: str,
    verify: bool = Query(True),
) -> Dict[str, Any]:
    """
    GET /api/forensics/sessions/{session_id}/export?verify=true

    Export full JSON evidence bundle with chain verification.
    """
    exporter = _get_exporter()
    try:
        bundle = await exporter.export_json(session_id, verify_chain=verify)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return bundle


@router.get("/sessions/{session_id}/export-csv")
async def export_session_csv(session_id: str) -> StreamingResponse:
    """
    GET /api/forensics/sessions/{session_id}/export-csv

    Download a CSV evidence log.
    """
    exporter = _get_exporter()
    try:
        csv_text = await exporter.export_csv(session_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))

    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="forensics_{session_id}.csv"'
        },
    )


@router.get("/sessions/{session_id}/replay")
async def replay_session_sse(
    session_id: str,
    speed: float = Query(2.0),
    from_timestamp: Optional[float] = Query(None),
    event_types: Optional[str] = Query(None, description="Comma-separated event types to include"),
) -> StreamingResponse:
    """
    GET /api/forensics/sessions/{session_id}/replay

    Server-Sent Events stream: replays the session timeline at speed× with
    original relative timing (capped at 5s gaps).

    Query params:
      speed: 0.5 | 1.0 | 2.0 | 5.0 | 10.0  (default 2.0)
      from_timestamp: Unix timestamp to start from
      event_types: e.g. "tool_call,firewall_detect"
    """
    replayer = _get_replayer()

    et_list: Optional[List[str]] = None
    if event_types:
        et_list = [t.strip() for t in event_types.split(",") if t.strip()]

    async def _stream():
        async for chunk in replayer.replay_stream(
            session_id=session_id,
            speed=speed,
            from_timestamp=from_timestamp,
            event_types=et_list,
        ):
            yield chunk

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
