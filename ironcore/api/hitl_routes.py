"""
HITL (Human-In-The-Loop) API Routes — Phase 5, Security V3.

Endpoints consumed by ChatGPT UI V3 (HITL Approvals panel):

  GET  /api/enterprise/hitl/pending        → pending requests (filtered by caller role)
  POST /api/enterprise/hitl/{id}/approve   → approve + reason + approver_id
  POST /api/enterprise/hitl/{id}/reject    → reject + reason
  GET  /api/enterprise/hitl/history        → paginated decisions (all statuses)
  GET  /api/enterprise/hitl/{id}/audit     → full audit chain for one request
  GET  /api/enterprise/hitl/stats          → approval stats (counts, avg time)

Works with both:
  a) The existing ironcore/enterprise/hitl/engine.py (via set_hitl_engine())
  b) Standalone mode with in-memory store (for testing / Phase 5 scope)

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from ironcore.api.enterprise_auth import require_enterprise, require_admin, EnterprisePrincipal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["HITL"])

# Injected HITL engine (from existing ironcore/enterprise/hitl/engine.py)
_hitl_engine = None

# Fallback in-memory store when engine is not injected
_requests: Dict[str, Dict[str, Any]] = {}
_audit_chains: Dict[str, List[Dict[str, Any]]] = {}


def set_hitl_engine(engine: Any) -> None:
    """Called at startup to inject the shared HITL engine."""
    global _hitl_engine
    _hitl_engine = engine
    logger.info("[HITLRoutes] HITL engine registered.")


def _get_all_requests() -> List[Dict[str, Any]]:
    """Return requests from the engine or fallback in-memory store."""
    if _hitl_engine is not None and hasattr(_hitl_engine, "_requests"):
        return list(_hitl_engine._requests.values())
    return list(_requests.values())


def _hash_entry(prev_hash: str, content: str) -> str:
    """Simple audit hash chain entry."""
    import hashlib
    return hashlib.sha256(f"{prev_hash}{content}".encode()).hexdigest()


def _append_audit(request_id: str, action: str, actor: str, reason: str = "") -> None:
    chain = _audit_chains.setdefault(request_id, [])
    prev_hash = chain[-1]["entry_hash"] if chain else ""
    content = f"{request_id}:{action}:{actor}:{reason}:{time.time()}"
    entry = {
        "request_id": request_id,
        "action": action,
        "actor": actor,
        "reason": reason,
        "timestamp": time.time(),
        "prev_hash": prev_hash,
        "entry_hash": _hash_entry(prev_hash, content),
    }
    chain.append(entry)


# ── Request models ─────────────────────────────────────────────────────────────

class ApproveRequest(BaseModel):
    reason: str = ""
    approver_id: str


class RejectRequest(BaseModel):
    reason: str
    rejector_id: str = "unknown"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/pending")
async def list_pending_hitl(
    role: Optional[str] = Query(None, description="Filter by role: team_lead|manager|admin"),
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> List[Dict[str, Any]]:
    """
    GET /api/enterprise/hitl/pending?role=team_lead

    Return pending HITL requests, optionally filtered by the approver role.
    """
    all_reqs = _get_all_requests()
    pending = [r for r in all_reqs if r.get("status", "").startswith("pending")]

    if role:
        # Filter by current level's required role
        pending = [
            r for r in pending
            if _current_level_role(r) == role
        ]

    return sorted(pending, key=lambda r: r.get("created_at", 0))


def _current_level_role(req: Dict[str, Any]) -> str:
    """Extract the role required at the current approval level."""
    chain = req.get("approval_chain", [])
    current_level = req.get("current_level", 1)
    for level in chain:
        if isinstance(level, dict) and level.get("level") == current_level:
            return level.get("role_required", "admin")
    return "admin"


@router.post("/{request_id}/approve")
async def approve_hitl(
    request_id: str,
    body: ApproveRequest,
    _: EnterprisePrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """
    POST /api/enterprise/hitl/{request_id}/approve

    Approve the current approval level. If multi-level, escalate to next level;
    if this is the final level, mark as approved.
    """
    req = None
    if _hitl_engine is not None and hasattr(_hitl_engine, "_requests"):
        req = _hitl_engine._requests.get(request_id)
    else:
        req = _requests.get(request_id)

    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"HITL request '{request_id}' not found")

    if req.get("status") not in ("pending", "pending_l1", "pending_l2", "pending_l3"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Request is not pending (status={req.get('status')})")

    now = time.time()
    current_level = req.get("current_level", 1)
    chain = req.get("approval_chain", [])
    max_level = max((l.get("level", 1) for l in chain if isinstance(l, dict)), default=1)

    decision = {
        "level": current_level,
        "action": "approved",
        "actor": body.approver_id,
        "reason": body.reason,
        "timestamp": now,
    }
    req.setdefault("decisions", []).append(decision)
    _append_audit(request_id, "approved", body.approver_id, body.reason)

    if current_level >= max_level:
        req["status"] = "approved"
        req["resolved_at"] = now
    else:
        next_level = current_level + 1
        req["current_level"] = next_level
        req["status"] = f"pending_l{next_level}"
        # Update SLA for next level
        for level in chain:
            if isinstance(level, dict) and level.get("level") == next_level:
                timeout_min = level.get("timeout_minutes", 10)
                req["sla_expires_at"] = now + timeout_min * 60
                break

    if _hitl_engine is not None and hasattr(_hitl_engine, "_requests"):
        _hitl_engine._requests[request_id] = req
    else:
        _requests[request_id] = req

    return {"request_id": request_id, "status": req["status"], "decision": decision}


@router.post("/{request_id}/reject")
async def reject_hitl(
    request_id: str,
    body: RejectRequest,
    _: EnterprisePrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """
    POST /api/enterprise/hitl/{request_id}/reject

    Reject a HITL request at any level. Immediately terminates the chain.
    """
    req = None
    if _hitl_engine is not None and hasattr(_hitl_engine, "_requests"):
        req = _hitl_engine._requests.get(request_id)
    else:
        req = _requests.get(request_id)

    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"HITL request '{request_id}' not found")

    if not req.get("status", "").startswith("pending"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Request is not pending (status={req.get('status')})")

    now = time.time()
    decision = {
        "level": req.get("current_level", 1),
        "action": "rejected",
        "actor": body.rejector_id,
        "reason": body.reason,
        "timestamp": now,
    }
    req.setdefault("decisions", []).append(decision)
    req["status"] = "rejected"
    req["resolved_at"] = now
    _append_audit(request_id, "rejected", body.rejector_id, body.reason)

    if _hitl_engine is not None and hasattr(_hitl_engine, "_requests"):
        _hitl_engine._requests[request_id] = req
    else:
        _requests[request_id] = req

    return {"request_id": request_id, "status": "rejected", "decision": decision}


@router.get("/history")
async def hitl_history(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> Dict[str, Any]:
    """
    GET /api/enterprise/hitl/history?status=approved&limit=20

    Paginated history of all HITL requests, newest first.
    """
    all_reqs = list(reversed(_get_all_requests()))
    if status_filter:
        all_reqs = [r for r in all_reqs if r.get("status") == status_filter]

    total = len(all_reqs)
    page = all_reqs[offset : offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "requests": page}


@router.get("/{request_id}/audit")
async def hitl_audit_chain(
    request_id: str,
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> Dict[str, Any]:
    """
    GET /api/enterprise/hitl/{request_id}/audit

    Return the full audit chain for a specific HITL request with integrity verification.
    """
    chain = _audit_chains.get(request_id, [])
    # Verify chain integrity
    chain_valid = True
    for i, entry in enumerate(chain):
        if i == 0:
            continue
        expected_prev = chain[i - 1]["entry_hash"]
        if entry["prev_hash"] != expected_prev:
            chain_valid = False
            break

    return {
        "request_id": request_id,
        "chain_valid": chain_valid,
        "entry_count": len(chain),
        "entries": chain,
    }


@router.get("/stats")
async def hitl_stats(
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> Dict[str, Any]:
    """
    GET /api/enterprise/hitl/stats

    Aggregated stats: approval rates, avg resolution time, counts by status.
    """
    all_reqs = _get_all_requests()
    status_counts: Dict[str, int] = {}
    resolution_times: List[float] = []

    for req in all_reqs:
        s = req.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1
        if req.get("resolved_at") and req.get("created_at"):
            resolution_times.append(req["resolved_at"] - req["created_at"])

    avg_resolution_secs = (
        sum(resolution_times) / len(resolution_times) if resolution_times else 0.0
    )
    total = len(all_reqs)
    approved = status_counts.get("approved", 0)
    rejected = status_counts.get("rejected", 0)

    return {
        "total_requests": total,
        "status_counts": status_counts,
        "approval_rate": round(approved / total, 3) if total > 0 else 0.0,
        "rejection_rate": round(rejected / total, 3) if total > 0 else 0.0,
        "avg_resolution_seconds": round(avg_resolution_secs, 2),
        "avg_resolution_minutes": round(avg_resolution_secs / 60, 2),
    }
