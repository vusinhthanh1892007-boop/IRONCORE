"""
Prompt Firewall AI — Core Gate (Phase 1, Security V3).

Wraps the existing 3-layer PromptScanner and extends it with:
  1. Custom admin-defined regex rules (FirewallRuleStore / TOML)
  2. Per-session detection counter → auto-quarantine
  3. SIEM telemetry hook on every detection event

Usage::

    firewall = PromptFirewall.from_env()
    result = await firewall.evaluate(prompt, session_id="sess-abc", user_id="u123")
    if not result.allowed:
        raise PermissionError(result.blocked_by)

Env vars:
    IRONCORE_FIREWALL_QUARANTINE_THRESHOLD  (int,  default 3)
    IRONCORE_FIREWALL_QUARANTINE_TTL        (int,  default 3600 seconds)
    IRONCORE_FIREWALL_RULES_PATH            (str,  path to TOML rules file)
    IRONCORE_FIREWALL_SIEM_ENABLED          (bool, default true)
    IRONCORE_FIREWALL_ENABLED               (bool, default true)
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ironcore.security.firewall_rules import (
    DEFAULT_RULES_PATH,
    FirewallRule,
    FirewallRuleAction,
    FirewallRuleStore,
)
from ironcore.security.prompt_scanner import (
    PromptScanner,
    ScanAction,
    ScanResult,
)

logger = logging.getLogger(__name__)

# ── Config from environment ───────────────────────────────────────────────────

_ENABLED = os.environ.get("IRONCORE_FIREWALL_ENABLED", "true").lower() != "false"
_QUARANTINE_THRESHOLD = int(
    os.environ.get("IRONCORE_FIREWALL_QUARANTINE_THRESHOLD", "3")
)
_QUARANTINE_TTL = int(
    os.environ.get("IRONCORE_FIREWALL_QUARANTINE_TTL", "3600")
)
_RULES_PATH_STR = os.environ.get("IRONCORE_FIREWALL_RULES_PATH", str(DEFAULT_RULES_PATH))
_SIEM_ENABLED = os.environ.get("IRONCORE_FIREWALL_SIEM_ENABLED", "true").lower() != "false"


# ── Models ────────────────────────────────────────────────────────────────────

class SessionState(BaseModel):
    """Tracking state per session — detection count, quarantine status."""

    session_id: str
    detection_count: int = 0
    last_detection: Optional[float] = None
    quarantined: bool = False
    quarantine_reason: str = ""
    quarantine_at: Optional[float] = None
    quarantine_by: str = "system"          # "system" or admin user_id
    warning_count: int = 0                 # count of WARN-level detections


class FirewallResult(BaseModel):
    """Unified result returned by PromptFirewall.evaluate()."""

    allowed: bool
    action: str                            # FirewallRuleAction value
    triggered_rule_ids: List[str] = Field(default_factory=list)
    triggered_rule_names: List[str] = Field(default_factory=list)
    risk_score: float = 0.0               # 0.0 – 1.0
    category: str = "clean"               # threat category from scanner
    evidence_snippet: str = ""            # first 100 chars of matched text
    session_quarantined: bool = False
    siem_event_emitted: bool = False
    blocked_by: str = ""                  # human-readable reason, if blocked
    scan_time_ms: float = 0.0


# ── PromptFirewall ────────────────────────────────────────────────────────────

class PromptFirewall:
    """
    AI Prompt Firewall — enterprise-grade gate before every LLM call.

    Pipeline (for a given prompt string):
      1. Check session quarantine (fast-exit if already quarantined)
      2. Run custom admin rules from FirewallRuleStore (first-match)
      3. Run 3-layer PromptScanner (regex + heuristic + optional LLM judge)
      4. Merge decisions (highest severity wins)
      5. Update session detection counter; quarantine if threshold reached
      6. Emit SIEM event via FirewallTelemetry (fire-and-forget)
      7. Return FirewallResult
    """

    def __init__(
        self,
        rule_store: Optional[FirewallRuleStore] = None,
        scanner: Optional[PromptScanner] = None,
        telemetry: Optional[Any] = None,         # FirewallTelemetry (circular-import safe)
        quarantine_threshold: int = _QUARANTINE_THRESHOLD,
        quarantine_ttl_seconds: int = _QUARANTINE_TTL,
        enabled: bool = _ENABLED,
    ) -> None:
        self._rule_store = rule_store or FirewallRuleStore()
        self._scanner = scanner or PromptScanner()
        self._telemetry = telemetry                # optional, set later
        self._quarantine_threshold = quarantine_threshold
        self._quarantine_ttl = quarantine_ttl_seconds
        self._enabled = enabled
        # In-memory session state (could be backed by Redis in production)
        self._sessions: Dict[str, SessionState] = {}

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, telemetry: Optional[Any] = None) -> "PromptFirewall":
        """
        Build a fully configured PromptFirewall from environment variables.
        Loads custom TOML rules from IRONCORE_FIREWALL_RULES_PATH.
        """
        rules_path = Path(_RULES_PATH_STR)
        rule_store = FirewallRuleStore(rules_path=rules_path)
        rule_store.load_from_file()                # sync load at startup
        return cls(
            rule_store=rule_store,
            telemetry=telemetry,
            quarantine_threshold=_QUARANTINE_THRESHOLD,
            quarantine_ttl_seconds=_QUARANTINE_TTL,
            enabled=_ENABLED,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def evaluate(
        self,
        prompt: str,
        session_id: str,
        user_id: str = "",
        context: Optional[str] = None,
    ) -> FirewallResult:
        """
        Evaluate prompt against all firewall layers.

        Args:
            prompt:     Raw user input or tool output to inspect.
            session_id: Current session identifier.
            user_id:    Current user identifier (for audit trail).
            context:    Optional system/accumulated context (for indirect injection scan).

        Returns:
            FirewallResult — check `allowed` before proceeding.
        """
        if not self._enabled:
            return FirewallResult(allowed=True, action=FirewallRuleAction.ALLOW)

        state = self._get_or_create_session(session_id)

        # ── Step 1: Quarantine fast-exit ─────────────────────────────────────
        if state.quarantined:
            if self._is_quarantine_expired(state):
                # Auto-release on TTL expiry
                state.quarantined = False
                state.detection_count = 0
                logger.info(
                    "[PromptFirewall] Quarantine TTL expired — session released | session=%s",
                    session_id,
                )
            else:
                return FirewallResult(
                    allowed=False,
                    action=FirewallRuleAction.QUARANTINE,
                    session_quarantined=True,
                    blocked_by=(
                        f"Session quarantined: {state.quarantine_reason}. "
                        f"Contact admin to release."
                    ),
                )

        t0 = time.perf_counter()

        # ── Step 2: Custom admin rules ───────────────────────────────────────
        custom_action, custom_rule = self._run_custom_rules(prompt)

        # ── Step 3: 3-layer scanner ──────────────────────────────────────────
        scan_result: ScanResult = await self._scanner.scan(prompt, context=context)

        scan_ms = (time.perf_counter() - t0) * 1000

        # ── Step 4: Merge decisions ──────────────────────────────────────────
        final_action = self._merge_actions(custom_action, scan_result.action)
        risk_score = max(
            scan_result.confidence,
            self._action_to_risk(custom_action),
        )

        # Collect triggered rule info
        triggered_ids: List[str] = []
        triggered_names: List[str] = []
        if custom_rule is not None:
            triggered_ids.append(custom_rule.id)
            triggered_names.append(custom_rule.name)

        evidence = scan_result.evidence[:100] if scan_result.evidence else ""
        category = scan_result.category.value if scan_result.category else "clean"

        # ── Step 5: Update session state ─────────────────────────────────────
        is_detection = final_action not in (
            FirewallRuleAction.ALLOW, FirewallRuleAction.WARN
        )
        if final_action == FirewallRuleAction.WARN:
            state.warning_count += 1
        if is_detection:
            state.detection_count += 1
            state.last_detection = time.time()

        # Quarantine if threshold reached
        session_quarantined = False
        if state.detection_count >= self._quarantine_threshold:
            state.quarantined = True
            state.quarantine_at = time.time()
            state.quarantine_reason = (
                f"Automatic quarantine after {state.detection_count} detections. "
                f"Last category: {category}"
            )
            state.quarantine_by = "system"
            final_action = FirewallRuleAction.QUARANTINE
            session_quarantined = True
            logger.warning(
                "[PromptFirewall] Session QUARANTINED | session=%s detections=%d",
                session_id,
                state.detection_count,
            )

        allowed = final_action in (FirewallRuleAction.ALLOW, FirewallRuleAction.WARN)
        blocked_by = ""
        if not allowed:
            blocked_by = (
                f"Prompt blocked by firewall: action={final_action} "
                f"category={category} confidence={risk_score:.2f}"
            )

        result = FirewallResult(
            allowed=allowed,
            action=final_action,
            triggered_rule_ids=triggered_ids,
            triggered_rule_names=triggered_names,
            risk_score=round(risk_score, 4),
            category=category,
            evidence_snippet=evidence,
            session_quarantined=session_quarantined,
            scan_time_ms=round(scan_ms, 3),
            blocked_by=blocked_by,
        )

        # ── Step 6: SIEM telemetry (fire-and-forget) ─────────────────────────
        if self._telemetry is not None and is_detection and _SIEM_ENABLED:
            try:
                import asyncio
                asyncio.ensure_future(
                    self._telemetry.emit_detection(result, session_id, evidence)
                )
                result.siem_event_emitted = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("[PromptFirewall] SIEM emit failed: %s", exc)

        if not allowed:
            logger.warning(
                "[PromptFirewall] BLOCKED | session=%s action=%s category=%s score=%.2f",
                session_id, final_action, category, risk_score,
            )
        return result

    # ── Session management ────────────────────────────────────────────────────

    def get_session_state(self, session_id: str) -> Optional[SessionState]:
        """Return current session state, or None if no activity recorded."""
        return self._sessions.get(session_id)

    def release_quarantine(self, session_id: str, admin_id: str = "admin") -> bool:
        """
        Admin-initiated quarantine release.
        Returns True if the session was quarantined and is now released.
        """
        state = self._sessions.get(session_id)
        if state and state.quarantined:
            state.quarantined = False
            state.detection_count = 0
            state.quarantine_reason = ""
            logger.info(
                "[PromptFirewall] Quarantine released by admin=%s | session=%s",
                admin_id, session_id,
            )
            return True
        return False

    def list_quarantined_sessions(self) -> List[SessionState]:
        """Return all currently quarantined sessions."""
        return [s for s in self._sessions.values() if s.quarantined]

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """
        Aggregate stats for the /api/security/firewall/stats endpoint.
        Returns counts suitable for a dashboard.
        """
        total = len(self._sessions)
        quarantined = sum(1 for s in self._sessions.values() if s.quarantined)
        total_detections = sum(s.detection_count for s in self._sessions.values())
        total_warnings = sum(s.warning_count for s in self._sessions.values())
        custom_rule_count = self._rule_store.rule_count()
        return {
            "enabled": self._enabled,
            "total_sessions_tracked": total,
            "quarantined_sessions": quarantined,
            "total_detections": total_detections,
            "total_warnings": total_warnings,
            "quarantine_threshold": self._quarantine_threshold,
            "quarantine_ttl_seconds": self._quarantine_ttl,
            "custom_rule_count": custom_rule_count,
            "siem_enabled": _SIEM_ENABLED,
        }

    # ── Rule store delegation ─────────────────────────────────────────────────

    @property
    def rule_store(self) -> FirewallRuleStore:
        return self._rule_store

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_or_create_session(self, session_id: str) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id)
        return self._sessions[session_id]

    def _is_quarantine_expired(self, state: SessionState) -> bool:
        if state.quarantine_at is None:
            return False
        return (time.time() - state.quarantine_at) >= self._quarantine_ttl

    def _run_custom_rules(
        self, text: str
    ) -> tuple[str, Optional[FirewallRule]]:
        """
        Evaluate the custom admin rules against *text*.
        First-match semantic — returns (action, matched_rule | None).
        """
        for rule in self._rule_store.get_active_rules():
            if rule.match(text):
                logger.info(
                    "[PromptFirewall] Custom rule triggered | rule=%s action=%s",
                    rule.name, rule.action,
                )
                return rule.action, rule
        return FirewallRuleAction.ALLOW, None

    @staticmethod
    def _merge_actions(custom_action: str, scan_action: ScanAction) -> str:
        """
        Merge custom rule action with scanner action.
        Highest severity wins.
        """
        _severity_rank = {
            FirewallRuleAction.ALLOW:      0,
            FirewallRuleAction.WARN:       1,
            FirewallRuleAction.SANITIZE:   2,
            FirewallRuleAction.BLOCK:      3,
            FirewallRuleAction.QUARANTINE: 4,
        }
        scan_str = scan_action.value  # ScanAction enum → str
        return max(
            custom_action,
            scan_str,
            key=lambda a: _severity_rank.get(a, 0),
        )

    @staticmethod
    def _action_to_risk(action: str) -> float:
        """Convert action severity to a risk score 0.0–1.0 for display."""
        return {
            FirewallRuleAction.ALLOW:      0.0,
            FirewallRuleAction.WARN:       0.30,
            FirewallRuleAction.SANITIZE:   0.60,
            FirewallRuleAction.BLOCK:      0.85,
            FirewallRuleAction.QUARANTINE: 1.0,
        }.get(action, 0.0)
