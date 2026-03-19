"""
Firewall API Routes — Phase 1, Security V3.

Exposes HTTP endpoints for ChatGPT UI V3 to:
  - View firewall stats and quarantined sessions
  - Manage custom firewall rules (CRUD + test)
  - Release quarantined sessions (admin only)

All write endpoints require admin JWT (enterprise only).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ironcore.api.auth import APIKeyAuth, AuthenticatedPrincipal
from ironcore.security.firewall_rules import FirewallRule
from ironcore.security.prompt_firewall import FirewallResult, PromptFirewall, SessionState

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Firewall"])

# Module-level singleton — injected at server startup via set_firewall()
_firewall: Optional[PromptFirewall] = None


def set_firewall(fw: PromptFirewall) -> None:
    """Called from server startup to inject the shared PromptFirewall instance."""
    global _firewall
    _firewall = fw
    logger.info("[FirewallRoutes] PromptFirewall instance registered.")


def _get_firewall() -> PromptFirewall:
    if _firewall is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firewall not initialized",
        )
    return _firewall


# ── Request / Response models ─────────────────────────────────────────────────

class RuleTestRequest(BaseModel):
    input_text: str


class TestPromptRequest(BaseModel):
    prompt: str
    session_id: str = "test-session"
    user_id: str = "admin"


class AddRuleRequest(BaseModel):
    name: str
    pattern: str
    category: str = "custom"
    action: str = "block"
    severity: str = "medium"
    description: str = ""
    enabled: bool = True


class ReleaseQuarantineRequest(BaseModel):
    admin_id: str = "admin"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_firewall_stats(
    fw: PromptFirewall = Depends(_get_firewall),
) -> Dict[str, Any]:
    """
    GET /api/security/firewall/stats

    Returns aggregate detection stats, session counts, and config.
    """
    return fw.get_stats()


@router.get("/sessions/quarantined")
async def list_quarantined_sessions(
    fw: PromptFirewall = Depends(_get_firewall),
) -> List[Dict[str, Any]]:
    """
    GET /api/security/firewall/sessions/quarantined

    Lists all currently quarantined sessions.
    """
    sessions = fw.list_quarantined_sessions()
    return [s.model_dump() for s in sessions]


@router.post("/sessions/{session_id}/release")
async def release_quarantine(
    session_id: str,
    body: ReleaseQuarantineRequest,
    fw: PromptFirewall = Depends(_get_firewall),
) -> Dict[str, Any]:
    """
    POST /api/security/firewall/sessions/{session_id}/release

    Admin action: release a quarantined session.
    """
    released = fw.release_quarantine(session_id, admin_id=body.admin_id)
    if not released:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found or not quarantined",
        )
    return {"session_id": session_id, "released": True, "released_by": body.admin_id}


@router.get("/sessions/{session_id}")
async def get_session_state(
    session_id: str,
    fw: PromptFirewall = Depends(_get_firewall),
) -> Dict[str, Any]:
    """
    GET /api/security/firewall/sessions/{session_id}

    Returns the current firewall state for one session.
    """
    state: Optional[SessionState] = fw.get_session_state(session_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No firewall data for session '{session_id}'",
        )
    return state.model_dump()


# ── Custom rules CRUD ─────────────────────────────────────────────────────────

@router.get("/rules")
async def list_rules(
    active_only: bool = False,
    fw: PromptFirewall = Depends(_get_firewall),
) -> List[Dict[str, Any]]:
    """
    GET /api/security/firewall/rules?active_only=false

    Lists all custom firewall rules.
    """
    if active_only:
        rules = fw.rule_store.get_active_rules()
    else:
        rules = fw.rule_store.get_all_rules()
    return [r.model_dump(exclude={"_compiled"}) for r in rules]


@router.post("/rules", status_code=status.HTTP_201_CREATED)
async def add_rule(
    body: AddRuleRequest,
    fw: PromptFirewall = Depends(_get_firewall),
) -> Dict[str, Any]:
    """
    POST /api/security/firewall/rules

    Create a new custom firewall rule.
    Returns the created rule including auto-generated id.
    """
    rule = FirewallRule(
        name=body.name,
        pattern=body.pattern,
        category=body.category,
        action=body.action,
        severity=body.severity,
        description=body.description,
        enabled=body.enabled,
        created_by="admin",
    )
    try:
        await fw.rule_store.add_rule(rule)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return rule.model_dump(exclude={"_compiled"})


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: str,
    fw: PromptFirewall = Depends(_get_firewall),
) -> None:
    """
    DELETE /api/security/firewall/rules/{rule_id}

    Remove a custom rule by id.
    """
    removed = await fw.rule_store.remove_rule(rule_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rule '{rule_id}' not found",
        )


@router.post("/rules/{rule_id}/test")
async def test_rule(
    rule_id: str,
    body: RuleTestRequest,
    fw: PromptFirewall = Depends(_get_firewall),
) -> Dict[str, Any]:
    """
    POST /api/security/firewall/rules/{rule_id}/test

    Dry-run a specific rule against the supplied input_text.
    Does NOT affect session state.
    """
    rule = fw.rule_store.get_rule(rule_id)
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rule '{rule_id}' not found",
        )
    return fw.rule_store.test_rule(rule, body.input_text)


@router.post("/test")
async def test_prompt(
    body: TestPromptRequest,
    fw: PromptFirewall = Depends(_get_firewall),
) -> Dict[str, Any]:
    """
    POST /api/security/firewall/test

    Run the full firewall evaluation on an input without actually blocking session.
    Useful for testing prompt content from the admin UI.
    Returns FirewallResult.
    """
    result: FirewallResult = await fw.evaluate(
        prompt=body.prompt,
        session_id=body.session_id,
        user_id=body.user_id,
    )
    return result.model_dump()
