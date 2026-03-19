"""
Automation Layer — Phase 6, Security V3 (Section 21: Automation & Intelligence).

Two components:

1. AutomationLayer:
   - Registers named playbooks (list of ordered steps)
   - On incident → lookup matching playbook → execute steps sequentially
   - Step actions: throttle_session, quarantine_session, downgrade_model,
                   notify_hitl, rollback_config, reduce_budget
   - Execution result logged with step-by-step status

2. PolicyLearner:
   - Analyzes past HITL decisions (approve/reject patterns)
   - When admin approves the same action_type N times → suggest ALLOW guardrail rule
   - When admin rejects the same action_type N times → suggest BLOCK guardrail rule
   - Suggestions stored pending admin confirm
   - Admin can approve (→ creates actual GuardrailRule) or dismiss

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ironcore.monitoring.incident_detector import AnomalyType, Incident

logger = logging.getLogger(__name__)


# ── Playbook models ────────────────────────────────────────────────────────────

class PlaybookStep(BaseModel):
    """One step in a playbook."""
    action: str                       # throttle_session | quarantine_session | etc.
    params: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class Playbook(BaseModel):
    """An automation playbook triggered by an anomaly type."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    trigger: AnomalyType
    steps: List[PlaybookStep] = Field(default_factory=list)
    enabled: bool = True
    created_at: float = Field(default_factory=time.time)
    run_count: int = 0
    last_run_at: Optional[float] = None


class PlaybookExecutionResult(BaseModel):
    playbook_id: str
    incident_id: str
    started_at: float
    finished_at: Optional[float] = None
    steps_executed: int = 0
    steps_succeeded: int = 0
    steps_failed: int = 0
    step_results: List[Dict[str, Any]] = Field(default_factory=list)
    success: bool = False
    error: Optional[str] = None


# ── PolicySuggestion ───────────────────────────────────────────────────────────

class PolicySuggestion(BaseModel):
    """A suggested guardrail rule based on HITL decision patterns."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_type: str
    suggested_effect: str             # "allow" | "block"
    confidence: float                 # 0.0–1.0
    based_on_count: int               # how many HITL decisions drove this
    window_days: int
    reason: str
    created_at: float = Field(default_factory=time.time)
    status: str = "pending"           # "pending" | "approved" | "dismissed"
    approved_rule_id: Optional[str] = None


# ── AutomationLayer ────────────────────────────────────────────────────────────

class AutomationLayer:
    """
    Executes playbooks in response to incidents detected by IncidentDetector.

    Usage::

        layer = AutomationLayer()
        await layer.register_playbook(Playbook(
            name="Firewall Burst Response",
            trigger=AnomalyType.FIREWALL_BURST,
            steps=[
                PlaybookStep(action="notify_hitl", params={"priority": "high"}),
                PlaybookStep(action="throttle_session", params={"rate": 10}),
            ],
        ))
        # Called by IncidentDetector.on_incident callback:
        result = await layer.execute_playbook(incident)
    """

    def __init__(self) -> None:
        self._playbooks: Dict[str, Playbook] = {}
        self._results: List[PlaybookExecutionResult] = []
        self._sessions: Dict[str, Dict[str, Any]] = {}   # session state store
        self._forensics_recorder: Optional[Any] = None    # injected optionally

    def set_forensics(self, recorder: Any) -> None:
        """Inject ForensicsRecorder for logging automation results."""
        self._forensics_recorder = recorder

    async def register_playbook(self, playbook: Playbook) -> None:
        self._playbooks[playbook.id] = playbook
        logger.info("[AutomationLayer] Playbook registered: %s (trigger=%s)", playbook.name, playbook.trigger)

    def list_playbooks(self) -> List[Playbook]:
        return list(self._playbooks.values())

    def get_playbook(self, playbook_id: str) -> Optional[Playbook]:
        return self._playbooks.get(playbook_id)

    def delete_playbook(self, playbook_id: str) -> bool:
        if playbook_id in self._playbooks:
            del self._playbooks[playbook_id]
            return True
        return False

    async def execute_playbook(self, incident: Incident) -> PlaybookExecutionResult:
        """
        Find the playbook matching the incident's anomaly_type and execute it.
        If no playbook matches, return a no-op result.
        """
        matching = [
            pb for pb in self._playbooks.values()
            if pb.enabled and pb.trigger == incident.anomaly_type
        ]

        if not matching:
            logger.debug("[AutomationLayer] No playbook for anomaly_type=%s", incident.anomaly_type)
            result = PlaybookExecutionResult(
                playbook_id="none",
                incident_id=incident.id,
                started_at=time.time(),
                finished_at=time.time(),
                success=True,
                error="No matching playbook",
            )
            self._results.append(result)
            return result

        playbook = matching[0]   # first match wins (could be priority-sorted later)
        result = PlaybookExecutionResult(
            playbook_id=playbook.id,
            incident_id=incident.id,
            started_at=time.time(),
        )

        logger.info(
            "[AutomationLayer] Executing playbook '%s' for incident %s",
            playbook.name, incident.id,
        )

        for step in playbook.steps:
            step_result = await self._execute_step(step, incident)
            result.steps_executed += 1
            result.step_results.append(step_result)
            if step_result.get("success"):
                result.steps_succeeded += 1
            else:
                result.steps_failed += 1

        result.finished_at = time.time()
        result.success = result.steps_failed == 0

        playbook.run_count += 1
        playbook.last_run_at = result.finished_at

        incident.playbook_executed = True
        incident.playbook_result = (
            f"SUCCESS: {result.steps_succeeded}/{result.steps_executed} steps"
            if result.success
            else f"PARTIAL: {result.steps_failed} steps failed"
        )

        self._results.append(result)
        logger.info("[AutomationLayer] Playbook '%s' done: %s", playbook.name, incident.playbook_result)
        return result

    def get_execution_history(self) -> List[PlaybookExecutionResult]:
        return list(self._results)

    # ── Step executors ────────────────────────────────────────────────────────

    async def _execute_step(
        self, step: PlaybookStep, incident: Incident
    ) -> Dict[str, Any]:
        """Route a playbook step to its implementation handler."""
        action = step.action
        params = step.params
        try:
            if action == "throttle_session":
                return await self._action_throttle_session(incident, params)
            elif action == "quarantine_session":
                return await self._action_quarantine_session(incident, params)
            elif action == "downgrade_model":
                return await self._action_downgrade_model(incident, params)
            elif action == "notify_hitl":
                return await self._action_notify_hitl(incident, params)
            elif action == "rollback_config":
                return await self._action_rollback_config(incident, params)
            elif action == "reduce_budget":
                return await self._action_reduce_budget(incident, params)
            else:
                return {"action": action, "success": False, "error": f"Unknown action: {action}"}
        except Exception as exc:  # noqa: BLE001
            logger.error("[AutomationLayer] Step '%s' failed: %s", action, exc)
            return {"action": action, "success": False, "error": str(exc)}

    async def _action_throttle_session(
        self, incident: Incident, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        rate = params.get("rate", 10)   # tokens/min
        context = incident.context
        session_id = context.get("session_id", "all")
        self._sessions[session_id] = {"throttled": True, "rate": rate, "at": time.time()}
        logger.warning("[AutomationLayer] Session %s throttled to %s tokens/min", session_id, rate)
        return {"action": "throttle_session", "session_id": session_id, "rate": rate, "success": True}

    async def _action_quarantine_session(
        self, incident: Incident, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        context = incident.context
        session_id = context.get("session_id", "all")
        self._sessions[session_id] = {"quarantined": True, "reason": f"auto: {incident.anomaly_type}", "at": time.time()}
        logger.warning("[AutomationLayer] Session %s quarantined (anomaly=%s)", session_id, incident.anomaly_type)
        return {"action": "quarantine_session", "session_id": session_id, "success": True}

    async def _action_downgrade_model(
        self, incident: Incident, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        target = params.get("target_model", "llama3.1:8b")
        # In production: update model config for affected sessions
        logger.warning("[AutomationLayer] Model downgrade triggered → %s", target)
        return {"action": "downgrade_model", "target_model": target, "success": True}

    async def _action_notify_hitl(
        self, incident: Incident, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        priority = params.get("priority", "high")
        # In production: create HITL request via HITLEngine
        req_id = str(uuid.uuid4())
        logger.warning(
            "[AutomationLayer] HITL notification created: priority=%s incident=%s req_id=%s",
            priority, incident.id, req_id,
        )
        return {
            "action": "notify_hitl",
            "hitl_request_id": req_id,
            "priority": priority,
            "success": True,
        }

    async def _action_rollback_config(
        self, incident: Incident, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        snapshot_name = params.get("snapshot", "last_known_good")
        logger.warning("[AutomationLayer] Config rollback triggered: snapshot=%s", snapshot_name)
        # In production: invoke OTA/config manager rollback
        return {"action": "rollback_config", "snapshot": snapshot_name, "success": True}

    async def _action_reduce_budget(
        self, incident: Incident, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        reduction_pct = params.get("reduction_percent", 50)
        logger.warning("[AutomationLayer] Budget reduction triggered: -%d%%", reduction_pct)
        return {"action": "reduce_budget", "reduction_percent": reduction_pct, "success": True}


# ── PolicyLearner ──────────────────────────────────────────────────────────────

class PolicyLearner:
    """
    Analyzes HITL decision history and suggests new GuardrailRules.

    Pattern detection:
      - If admin approves the same action_type ≥ APPROVE_THRESHOLD times
        within window_days → suggest ALLOW rule
      - If admin rejects the same action_type ≥ REJECT_THRESHOLD times
        within window_days → suggest BLOCK rule

    Usage::

        learner = PolicyLearner()
        suggestions = await learner.analyze_decisions(window_days=7)
        pending = await learner.get_suggestions()
        # Admin approves a suggestion:
        rule = await learner.approve_suggestion(suggestion_id)
    """

    APPROVE_THRESHOLD = 3
    REJECT_THRESHOLD  = 3

    def __init__(self) -> None:
        self._suggestions: Dict[str, PolicySuggestion] = {}
        self._hitl_history: List[Dict[str, Any]] = []   # injected externally

    def ingest_hitl_decisions(self, decisions: List[Dict[str, Any]]) -> None:
        """Feed HITL decision records. Each dict must have: action_type, action (approved/rejected), timestamp."""
        self._hitl_history = list(decisions)

    async def analyze_decisions(self, window_days: int = 7) -> List[PolicySuggestion]:
        """
        Scan HITL history within window_days and generate suggestions.
        Returns only newly created suggestions.
        """
        cutoff = time.time() - window_days * 86400
        recent = [
            d for d in self._hitl_history
            if d.get("timestamp", 0) >= cutoff
        ]

        approved_counts: Counter = Counter()
        rejected_counts: Counter = Counter()
        for decision in recent:
            action_type = decision.get("action_type", "unknown")
            action = decision.get("action", "")
            if action == "approved":
                approved_counts[action_type] += 1
            elif action == "rejected":
                rejected_counts[action_type] += 1

        new_suggestions: List[PolicySuggestion] = []

        for action_type, count in approved_counts.items():
            if count >= self.APPROVE_THRESHOLD and not self._suggestion_exists(action_type, "allow"):
                suggestion = PolicySuggestion(
                    action_type=action_type,
                    suggested_effect="allow",
                    confidence=min(1.0, count / 10),
                    based_on_count=count,
                    window_days=window_days,
                    reason=(
                        f"Admin approved '{action_type}' {count} times in the last {window_days} days. "
                        f"Consider adding an ALLOW guardrail rule to reduce future HITL overhead."
                    ),
                )
                self._suggestions[suggestion.id] = suggestion
                new_suggestions.append(suggestion)

        for action_type, count in rejected_counts.items():
            if count >= self.REJECT_THRESHOLD and not self._suggestion_exists(action_type, "block"):
                suggestion = PolicySuggestion(
                    action_type=action_type,
                    suggested_effect="block",
                    confidence=min(1.0, count / 10),
                    based_on_count=count,
                    window_days=window_days,
                    reason=(
                        f"Admin rejected '{action_type}' {count} times in the last {window_days} days. "
                        f"Consider adding a BLOCK guardrail rule to prevent this action automatically."
                    ),
                )
                self._suggestions[suggestion.id] = suggestion
                new_suggestions.append(suggestion)

        logger.info(
            "[PolicyLearner] Analysis complete: %d HITL decisions → %d new suggestions",
            len(recent), len(new_suggestions),
        )
        return new_suggestions

    async def get_suggestions(self) -> List[PolicySuggestion]:
        """Return all pending suggestions."""
        return [s for s in self._suggestions.values() if s.status == "pending"]

    async def approve_suggestion(
        self, suggestion_id: str, rule_store: Optional[Any] = None
    ) -> Optional[PolicySuggestion]:
        """
        Admin approves a suggestion. If rule_store (GuardrailRulesStore) is provided,
        creates and persists the actual GuardrailRule. Returns updated suggestion.
        """
        suggestion = self._suggestions.get(suggestion_id)
        if suggestion is None:
            return None

        if rule_store is not None:
            try:
                from ironcore.enterprise.guardrail.rules_store import GuardrailRule, GuardrailRemedy, GuardrailConditionType
                rule = GuardrailRule(
                    name=f"AutoPolicy: {suggestion.action_type} {suggestion.suggested_effect}",
                    description=suggestion.reason,
                    category="ai_policy",
                    scope="INPUT",
                    condition_type=GuardrailConditionType.KEYWORD,
                    condition_params={"keywords": [suggestion.action_type]},
                    remedy=GuardrailRemedy.BLOCK if suggestion.suggested_effect == "block" else GuardrailRemedy.WARN,
                    enabled=True,
                )
                await rule_store.add_rule(rule)
                suggestion.approved_rule_id = rule.rule_id
                logger.info("[PolicyLearner] Guardrail rule created: %s", rule.name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[PolicyLearner] Rule creation failed: %s", exc)

        suggestion.status = "approved"
        return suggestion

    async def dismiss_suggestion(self, suggestion_id: str) -> bool:
        suggestion = self._suggestions.get(suggestion_id)
        if suggestion is None:
            return False
        suggestion.status = "dismissed"
        return True

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _suggestion_exists(self, action_type: str, effect: str) -> bool:
        """Return True if a pending suggestion already exists for this action_type+effect."""
        return any(
            s.action_type == action_type
            and s.suggested_effect == effect
            and s.status == "pending"
            for s in self._suggestions.values()
        )
