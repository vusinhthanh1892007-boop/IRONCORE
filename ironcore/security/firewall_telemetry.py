"""
Prompt Firewall — SIEM Telemetry Hook (Phase 1, Security V3).

Emits a CEF Security event to the SIEM streamer whenever the
Prompt Firewall detects or blocks a prompt.

Security note:
  Only a 50-character snippet of the evidence is emitted — NEVER the
  full raw prompt text, to respect data minimization principles.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ironcore.security.prompt_firewall import FirewallResult

logger = logging.getLogger(__name__)

_SNIPPET_MAX = 50   # max characters of evidence to include in the SIEM event


class FirewallTelemetry:
    """
    Bridge between PromptFirewall and the SIEM streamer.

    Args:
        siem_streamer: An object with an ``emit(event_dict)`` coroutine method.
                       If None, events are only logged locally.
    """

    def __init__(self, siem_streamer: Optional[object] = None) -> None:
        self._streamer = siem_streamer
        self._emit_count: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    async def emit_detection(
        self,
        result: "FirewallResult",
        session_id: str,
        evidence_snippet: str,
    ) -> None:
        """
        Build and emit a SIEM event for a firewall detection.

        Args:
            result:           The FirewallResult from PromptFirewall.evaluate().
            session_id:       Current session identifier.
            evidence_snippet: Raw evidence text — will be truncated to _SNIPPET_MAX chars.
        """
        # Truncate evidence — NEVER include full prompt
        safe_snippet = evidence_snippet[:_SNIPPET_MAX].replace("|", "\\|").replace("\n", " ")

        severity = self._action_to_siem_severity(result.action)
        cef = self._build_cef(result, session_id, safe_snippet, severity)
        event = {
            "source": "prompt_firewall",
            "event_type": "firewall_detection",
            "severity": self._action_to_level(result.action),
            "session_id": session_id,
            "action": result.action,
            "category": result.category,
            "risk_score": result.risk_score,
            "triggered_rules": result.triggered_rule_names,
            "evidence_snippet": safe_snippet,
            "session_quarantined": result.session_quarantined,
            "cef_line": cef,
            "timestamp": time.time(),
        }

        self._emit_count += 1

        if self._streamer is not None:
            try:
                await self._streamer.emit(event)
                logger.debug(
                    "[FirewallTelemetry] SIEM event emitted | session=%s action=%s",
                    session_id, result.action,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[FirewallTelemetry] SIEM emit failed: %s", exc)
        else:
            logger.info(
                "[FirewallTelemetry] (no streamer) SIEM event | session=%s action=%s category=%s snippet=%s",
                session_id, result.action, result.category, safe_snippet,
            )

    def get_emit_count(self) -> int:
        """Total number of SIEM events emitted since startup."""
        return self._emit_count

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_cef(
        result: "FirewallResult",
        session_id: str,
        snippet: str,
        severity: int,
    ) -> str:
        """
        Build a CEF (Common Event Format) log line.

        Format:
            CEF:0|IronCore|Enterprise|3.0|FIREWALL_DETECTION|Prompt Firewall|<sev>|<extensions>
        """
        rules_str = ",".join(result.triggered_rule_names) or "scanner"
        return (
            f"CEF:0|IronCore|Enterprise|3.0|FIREWALL_DETECTION|"
            f"Prompt Firewall Detection|{severity}|"
            f"sid={session_id} "
            f"act={result.action} "
            f"cat={result.category} "
            f"risk={result.risk_score:.2f} "
            f"rules={rules_str} "
            f"quarantine={int(result.session_quarantined)} "
            f"msg={snippet}"
        )

    @staticmethod
    def _action_to_siem_severity(action: str) -> int:
        """Map firewall action to CEF numeric severity (0–10)."""
        return {
            "allow":      0,
            "warn":       3,
            "sanitize":   5,
            "block":      7,
            "quarantine": 9,
        }.get(action, 5)

    @staticmethod
    def _action_to_level(action: str) -> str:
        """Map action to severity label for SIEM event dict."""
        return {
            "allow":      "info",
            "warn":       "low",
            "sanitize":   "medium",
            "block":      "high",
            "quarantine": "critical",
        }.get(action, "medium")
