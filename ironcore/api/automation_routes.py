"""
Automation & Intelligence API Routes — Phase 6, Security V3.

Endpoints consumed by ChatGPT UI V3 (Section 21 panel):

  GET  /api/monitoring/incidents              → active incidents
  GET  /api/monitoring/incidents/history      → all incidents (resolved too)
  POST /api/monitoring/incidents/{id}/resolve → manual resolve
  GET  /api/monitoring/playbooks              → registered playbooks
  POST /api/monitoring/playbooks              → register new playbook
  DELETE /api/monitoring/playbooks/{id}       → delete playbook
  POST /api/monitoring/playbooks/{id}/trigger → manually trigger playbook against incident
  GET  /api/monitoring/suggestions            → PolicyLearner pending suggestions
  POST /api/monitoring/suggestions/{id}/approve → Admin approve → create rule
  POST /api/monitoring/suggestions/{id}/dismiss  → Dismiss suggestion
  GET  /api/monitoring/alert-routing          → current AlertManager routing table
  POST /api/monitoring/alert-routing          → update routing for a severity level

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from ironcore.api.enterprise_auth import require_enterprise, require_admin, EnterprisePrincipal

from ironcore.monitoring.incident_detector import AnomalyType, Incident, IncidentDetector
from ironcore.monitoring.alert_manager import AlertManager, AlertChannel
from ironcore.monitoring.automation_layer import AutomationLayer, Playbook, PlaybookStep, PolicyLearner

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Automation & Intelligence"])

# Module-level singletons — injected via set_automation()
_detector:   Optional[IncidentDetector] = None
_alert_mgr:  Optional[AlertManager]     = None
_automation: Optional[AutomationLayer]  = None
_learner:    Optional[PolicyLearner]    = None


def set_automation(
    detector: IncidentDetector,
    alert_manager: AlertManager,
    automation: AutomationLayer,
    learner: PolicyLearner,
) -> None:
    """Called at server startup to inject shared singletons."""
    global _detector, _alert_mgr, _automation, _learner
    _detector   = detector
    _alert_mgr  = alert_manager
    _automation = automation
    _learner    = learner
    logger.info("[AutomationRoutes] Automation singletons registered.")


def _get_detector() -> IncidentDetector:
    if _detector is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "IncidentDetector not initialized")
    return _detector


def _get_automation() -> AutomationLayer:
    if _automation is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AutomationLayer not initialized")
    return _automation


def _get_learner() -> PolicyLearner:
    if _learner is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "PolicyLearner not initialized")
    return _learner


def _get_alert_mgr() -> AlertManager:
    if _alert_mgr is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AlertManager not initialized")
    return _alert_mgr


# ── Request models ─────────────────────────────────────────────────────────────

class CreatePlaybookRequest(BaseModel):
    name: str
    trigger: str                        # AnomalyType value string
    steps: List[Dict[str, Any]]
    enabled: bool = True


class UpdateRoutingRequest(BaseModel):
    severity: str
    channels: List[str]                 # AlertChannel value strings


# ── Incident endpoints ─────────────────────────────────────────────────────────

@router.get("/incidents")
async def list_active_incidents(
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> List[Dict[str, Any]]:
    """
    GET /api/monitoring/incidents

    Return all currently active (unresolved) incidents.
    """
    detector = _get_detector()
    return [i.model_dump() for i in detector.list_active_incidents()]


@router.get("/incidents/history")
async def list_all_incidents(
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> List[Dict[str, Any]]:
    """
    GET /api/monitoring/incidents/history

    Return all incidents (active + resolved), newest first.
    """
    detector = _get_detector()
    incidents = list(reversed(detector.list_all_incidents()))
    return [i.model_dump() for i in incidents]


@router.post("/incidents/{incident_id}/resolve")
async def resolve_incident(
    incident_id: str,
    _: EnterprisePrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """
    POST /api/monitoring/incidents/{incident_id}/resolve

    Manually resolve an active incident.
    """
    detector = _get_detector()
    ok = detector.resolve_incident(incident_id, manual=True)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Incident '{incident_id}' not found")
    return {"incident_id": incident_id, "status": "manually_resolved", "resolved_at": time.time()}


# ── Playbook endpoints ─────────────────────────────────────────────────────────

@router.get("/playbooks")
async def list_playbooks(
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> List[Dict[str, Any]]:
    """
    GET /api/monitoring/playbooks

    List all registered automation playbooks.
    """
    automation = _get_automation()
    return [pb.model_dump() for pb in automation.list_playbooks()]


@router.post("/playbooks", status_code=status.HTTP_201_CREATED)
async def create_playbook(
    body: CreatePlaybookRequest,
    _: EnterprisePrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """
    POST /api/monitoring/playbooks

    Register a new automation playbook.
    """
    automation = _get_automation()
    try:
        trigger = AnomalyType(body.trigger)
    except ValueError:
        valid = [t.value for t in AnomalyType]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"trigger must be one of {valid}")

    steps = [
        PlaybookStep(
            action=s.get("action", ""),
            params=s.get("params", {}),
            description=s.get("description", ""),
        )
        for s in body.steps
    ]
    playbook = Playbook(
        name=body.name,
        trigger=trigger,
        steps=steps,
        enabled=body.enabled,
    )
    await automation.register_playbook(playbook)
    return playbook.model_dump()


@router.delete("/playbooks/{playbook_id}")
async def delete_playbook(
    playbook_id: str,
    _: EnterprisePrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """DELETE /api/monitoring/playbooks/{playbook_id}"""
    automation = _get_automation()
    deleted = automation.delete_playbook(playbook_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Playbook '{playbook_id}' not found")
    return {"deleted": True, "playbook_id": playbook_id}


@router.post("/playbooks/{playbook_id}/trigger")
async def trigger_playbook(
    playbook_id: str,
    _: EnterprisePrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """
    POST /api/monitoring/playbooks/{playbook_id}/trigger

    Admin manually triggers a playbook — creates a synthetic incident and runs it.
    """
    automation = _get_automation()
    playbook = automation.get_playbook(playbook_id)
    if playbook is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Playbook '{playbook_id}' not found")

    # Create synthetic incident for manual trigger
    synthetic = Incident(
        anomaly_type=playbook.trigger,
        severity="medium",
        context={"manual_trigger": True, "playbook_id": playbook_id},
        suggested_actions=["Manually triggered by admin"],
    )
    result = await automation.execute_playbook(synthetic)
    return {
        "playbook_id": playbook_id,
        "incident_id": synthetic.id,
        "result": result.model_dump(),
    }


# ── PolicyLearner / suggestions endpoints ──────────────────────────────────────

@router.get("/suggestions")
async def list_suggestions(
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> List[Dict[str, Any]]:
    """
    GET /api/monitoring/suggestions

    Return pending PolicyLearner suggestions awaiting admin review.
    """
    learner = _get_learner()
    pending = await learner.get_suggestions()
    return [s.model_dump() for s in pending]


@router.post("/suggestions/analyze")
async def trigger_analysis(
    window_days: int = 7,
    _: EnterprisePrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """
    POST /api/monitoring/suggestions/analyze?window_days=7

    Manually trigger a PolicyLearner analysis pass.
    """
    learner = _get_learner()
    new = await learner.analyze_decisions(window_days=window_days)
    return {
        "analyzed": True,
        "window_days": window_days,
        "new_suggestions": len(new),
        "suggestions": [s.model_dump() for s in new],
    }


@router.post("/suggestions/{suggestion_id}/approve")
async def approve_suggestion(
    suggestion_id: str,
    _: EnterprisePrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """
    POST /api/monitoring/suggestions/{suggestion_id}/approve

    Admin approves a PolicyLearner suggestion → creates a GuardrailRule.
    """
    learner = _get_learner()
    approved = await learner.approve_suggestion(suggestion_id, rule_store=None)
    if approved is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Suggestion '{suggestion_id}' not found")
    return approved.model_dump()


@router.post("/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(
    suggestion_id: str,
    _: EnterprisePrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """
    POST /api/monitoring/suggestions/{suggestion_id}/dismiss

    Dismiss a PolicyLearner suggestion.
    """
    learner = _get_learner()
    ok = await learner.dismiss_suggestion(suggestion_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Suggestion '{suggestion_id}' not found")
    return {"suggestion_id": suggestion_id, "status": "dismissed"}


# ── AlertManager routing ───────────────────────────────────────────────────────

@router.get("/alert-routing")
async def get_alert_routing(
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> Dict[str, Any]:
    """GET /api/monitoring/alert-routing — return current AlertManager routing table."""
    mgr = _get_alert_mgr()
    return {
        "routing": mgr.get_routing(),
        "stats": {
            "alerts_sent": mgr.sent_count,
            "alerts_failed": mgr.failed_count,
        },
    }


@router.post("/alert-routing")
async def update_alert_routing(
    body: UpdateRoutingRequest,
    _: EnterprisePrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """
    POST /api/monitoring/alert-routing

    Update the alert routing channels for a given severity level.
    """
    mgr = _get_alert_mgr()
    try:
        channels = [AlertChannel(c) for c in body.channels]
    except ValueError as exc:
        valid = [c.value for c in AlertChannel]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid channel: {exc}. Valid: {valid}")

    await mgr.configure_routing(body.severity, channels)
    return {
        "severity": body.severity,
        "channels": [c.value for c in channels],
        "routing": mgr.get_routing(),
    }
