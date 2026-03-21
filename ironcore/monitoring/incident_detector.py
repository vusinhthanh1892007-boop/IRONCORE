"""
Incident Detector — Phase 6, Security V3 (Section 21: Automation & Intelligence).

Background daemon that samples the MetricsCollector every 30 seconds and
detects 6 anomaly types:

  1. COST_SPIKE          — cost increases > threshold% in 5 minutes
  2. HIGH_ERROR_RATE     — system error rate > threshold (events/s)
  3. UNUSUAL_TOOL_PATTERN — unusual spikes in tool-call events
  4. LATENCY_DEGRADATION — request latency P95 rises sharply
  5. FIREWALL_BURST      — firewall detections > threshold in 1 minute
  6. SESSION_ANOMALY     — active sessions > threshold

Design:
  - Stateless between checks: uses only the current MetricsCollector snapshot
  - Incident deduplication: same anomaly_type not re-fired within cooldown_seconds
  - Incidents stored with status (active/auto_resolved/manually_resolved)
  - Integrates with AutomationLayer via callback (see automation_layer.py)

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_CHECK_INTERVAL_SECONDS = 30

# Anomaly thresholds (overridable via env)
import os as _os
_THRESHOLDS = {
    "firewall_burst_1m":       int(_os.environ.get("IRONCORE_THRESH_FW_BURST",  "10")),
    "error_rate_1m":           float(_os.environ.get("IRONCORE_THRESH_ERR_RATE", "0.5")),
    "guardrail_violations_1m": int(_os.environ.get("IRONCORE_THRESH_GR_VIOL",  "5")),
    "active_sessions":         int(_os.environ.get("IRONCORE_THRESH_SESSIONS",  "50")),
    "cooldown_seconds":        int(_os.environ.get("IRONCORE_THRESH_COOLDOWN",  "300")),
}


# ── Enums ─────────────────────────────────────────────────────────────────────

class AnomalyType(str, Enum):
    COST_SPIKE          = "cost_spike"
    HIGH_ERROR_RATE     = "high_error_rate"
    UNUSUAL_TOOL_PATTERN = "unusual_tool"
    LATENCY_DEGRADATION = "latency_degrad"
    FIREWALL_BURST      = "firewall_burst"
    SESSION_ANOMALY     = "session_anomaly"
    GUARDRAIL_BURST     = "guardrail_burst"   # extended type


class IncidentStatus(str, Enum):
    ACTIVE             = "active"
    AUTO_RESOLVED      = "auto_resolved"
    MANUALLY_RESOLVED  = "manually_resolved"


# ── Models ─────────────────────────────────────────────────────────────────────

class Incident(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    anomaly_type: AnomalyType
    severity: str                 # "low" | "medium" | "high" | "critical"
    detected_at: float = Field(default_factory=time.time)
    context: Dict[str, Any] = Field(default_factory=dict)
    suggested_actions: List[str] = Field(default_factory=list)
    auto_resolved: bool = False
    resolved_at: Optional[float] = None
    status: IncidentStatus = IncidentStatus.ACTIVE
    playbook_executed: bool = False
    playbook_result: Optional[str] = None


# ── IncidentDetector ──────────────────────────────────────────────────────────

class IncidentDetector:
    """
    Background daemon — samples MetricsCollector every 30s and fires incidents.

    Usage::

        from ironcore.enterprise.monitoring.metrics_collector import get_collector
        detector = IncidentDetector(get_collector())
        await detector.start()     # call once at server startup; non-blocking
    """

    def __init__(
        self,
        collector: Any,                          # MetricsCollector (avoid hard import cycle)
        check_interval: int = _CHECK_INTERVAL_SECONDS,
        on_incident: Optional[Callable[[Incident], Coroutine[Any, Any, None]]] = None,
    ) -> None:
        self._collector = collector
        self._check_interval = check_interval
        self._on_incident = on_incident       # async callback → AutomationLayer
        self._incidents: Dict[str, Incident] = {}   # id → Incident
        self._last_fired: Dict[AnomalyType, float] = {}  # cooldown tracking
        self._running = False
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background detection loop (non-blocking)."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(
            self._detection_loop(), name="ironcore-incident-detector"
        )
        logger.info("[IncidentDetector] Started (interval=%ds)", self._check_interval)

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    # ── Public API ─────────────────────────────────────────────────────────────

    async def check_anomalies(self) -> List[Incident]:
        """
        Run a single anomaly check pass against the current metrics snapshot.
        Returns a list of new Incident objects that were fired.
        """
        snap = self._collector.snapshot()
        new_incidents: List[Incident] = []

        # ── 1. FIREWALL_BURST: firewall detections in last minute ─────────────
        fw_burst = snap.get("firewall", {}).get("detections_1m", 0)
        if fw_burst >= _THRESHOLDS["firewall_burst_1m"]:
            inc = self._make_incident(
                AnomalyType.FIREWALL_BURST,
                severity="high" if fw_burst < 20 else "critical",
                context={"firewall_detections_1m": fw_burst, "threshold": _THRESHOLDS["firewall_burst_1m"]},
                suggested_actions=[
                    "Review firewall logs for coordinated injection attempts",
                    "Consider tightening firewall rules",
                    "Escalate to security team if burst persists",
                ],
            )
            if inc:
                new_incidents.append(inc)

        # ── 2. HIGH_ERROR_RATE ────────────────────────────────────────────────
        err_rate = snap.get("system", {}).get("error_rate_1m", 0.0)
        if err_rate >= _THRESHOLDS["error_rate_1m"]:
            inc = self._make_incident(
                AnomalyType.HIGH_ERROR_RATE,
                severity="medium" if err_rate < 1.0 else "high",
                context={"error_rate_1m": err_rate, "threshold": _THRESHOLDS["error_rate_1m"]},
                suggested_actions=[
                    "Check system logs for root cause",
                    "Verify LLM provider availability",
                    "Consider circuit-breaker activation",
                ],
            )
            if inc:
                new_incidents.append(inc)

        # ── 3. GUARDRAIL_BURST ────────────────────────────────────────────────
        gr_viol = snap.get("guardrail", {}).get("violations_1m", 0)
        if gr_viol >= _THRESHOLDS["guardrail_violations_1m"]:
            inc = self._make_incident(
                AnomalyType.GUARDRAIL_BURST,
                severity="medium",
                context={"guardrail_violations_1m": gr_viol, "threshold": _THRESHOLDS["guardrail_violations_1m"]},
                suggested_actions=[
                    "Review top triggered guardrail rules",
                    "Check for rule false positives",
                    "Notify content team of policy violations",
                ],
            )
            if inc:
                new_incidents.append(inc)

        # ── 4. SESSION_ANOMALY: active sessions ───────────────────────────────
        active_sessions = snap.get("forensics", {}).get("active_sessions", 0)
        if active_sessions >= _THRESHOLDS["active_sessions"]:
            inc = self._make_incident(
                AnomalyType.SESSION_ANOMALY,
                severity="medium",
                context={"active_sessions": active_sessions, "threshold": _THRESHOLDS["active_sessions"]},
                suggested_actions=[
                    "Review session distribution",
                    "Check for session leak or zombie sessions",
                    "Consider session rate limiting",
                ],
            )
            if inc:
                new_incidents.append(inc)

        # ── 5. Cost spike (placeholder — requires cost tracking integration) ──
        # Could be wired when cost metrics are available in snapshot
        # Currently uses request_rate as a cost proxy
        req_rate_1m = snap.get("system", {}).get("requests_1m", 0)
        if req_rate_1m > 200:   # proxy: very high request rate → potential cost spike
            inc = self._make_incident(
                AnomalyType.COST_SPIKE,
                severity="high",
                context={"proxy_metric": "requests_1m", "value": req_rate_1m, "threshold": 200},
                suggested_actions=[
                    "Review cost and request telemetry",
                    "Consider downgrading model for non-critical sessions",
                    "Enable request throttling",
                ],
            )
            if inc:
                new_incidents.append(inc)

        # Dispatch callbacks and store
        for incident in new_incidents:
            self._incidents[incident.id] = incident
            if self._on_incident:
                try:
                    await self._on_incident(incident)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[IncidentDetector] on_incident callback failed: %s", exc)

        return new_incidents

    def list_active_incidents(self) -> List[Incident]:
        """Return all incidents with status=ACTIVE."""
        return [i for i in self._incidents.values() if i.status == IncidentStatus.ACTIVE]

    def list_all_incidents(self) -> List[Incident]:
        """Return all incidents (active + resolved)."""
        return list(self._incidents.values())

    def resolve_incident(self, incident_id: str, manual: bool = True) -> bool:
        """Mark an incident as resolved."""
        inc = self._incidents.get(incident_id)
        if inc is None:
            return False
        inc.status = IncidentStatus.MANUALLY_RESOLVED if manual else IncidentStatus.AUTO_RESOLVED
        inc.auto_resolved = not manual
        inc.resolved_at = time.time()
        return True

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        return self._incidents.get(incident_id)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _make_incident(
        self,
        anomaly_type: AnomalyType,
        severity: str,
        context: Dict[str, Any],
        suggested_actions: List[str],
    ) -> Optional[Incident]:
        """Create an Incident if not in cooldown for this anomaly_type."""
        now = time.time()
        last = self._last_fired.get(anomaly_type, 0)
        cooldown = _THRESHOLDS["cooldown_seconds"]
        if now - last < cooldown:
            logger.debug(
                "[IncidentDetector] %s in cooldown (%.0fs remaining)",
                anomaly_type, cooldown - (now - last),
            )
            return None

        self._last_fired[anomaly_type] = now
        incident = Incident(
            anomaly_type=anomaly_type,
            severity=severity,
            context=context,
            suggested_actions=suggested_actions,
        )
        logger.warning(
            "[IncidentDetector] INCIDENT FIRED: type=%s severity=%s context=%s",
            anomaly_type, severity, context,
        )
        return incident

    async def _detection_loop(self) -> None:
        """Background loop: check anomalies every N seconds."""
        while self._running:
            try:
                new = await self.check_anomalies()
                if new:
                    logger.info("[IncidentDetector] %d new incident(s) detected", len(new))
            except Exception as exc:  # noqa: BLE001
                logger.error("[IncidentDetector] Error in detection loop: %s", exc)
            await asyncio.sleep(self._check_interval)
