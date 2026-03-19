"""
Tests — Phase 6: Security V3 — Automation & Intelligence Layer.

Coverage (15 tests):
  1.  IncidentDetector: check_anomalies detects FIREWALL_BURST when threshold exceeded
  2.  IncidentDetector: cooldown prevents re-firing same anomaly within window
  3.  IncidentDetector: list_active_incidents returns only unresolved
  4.  IncidentDetector: resolve_incident marks as manually_resolved
  5.  IncidentDetector: HIGH_ERROR_RATE detected from metrics snapshot
  6.  AlertManager: default routing table has critical→SIEM+Telegram+Webhook
  7.  AlertManager: configure_routing updates the routing table
  8.  AlertManager: send_alert dispatches to SIEM channel (record_event call)
  9.  AutomationLayer: register_playbook stores and retrieves playbook
  10. AutomationLayer: execute_playbook runs steps and returns results
  11. AutomationLayer: notify_hitl step returns hitl_request_id
  12. AutomationLayer: no matching playbook → returns success with error field
  13. PolicyLearner: analyze_decisions detects APPROVE pattern → ALLOW suggestion
  14. PolicyLearner: analyze_decisions detects REJECT pattern → BLOCK suggestion
  15. PolicyLearner: approve_suggestion changes status to approved
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("IRONCORE_EDITION", "enterprise")


# ── Helpers ────────────────────────────────────────────────────────────────────

class MockCollector:
    """Fake MetricsCollector that returns a configurable snapshot."""
    def __init__(self, snap: Dict[str, Any]):
        self._snap = snap

    def snapshot(self) -> Dict[str, Any]:
        return self._snap


def _make_detector(snap: Dict[str, Any] = None):
    from ironcore.monitoring.incident_detector import IncidentDetector
    snap = snap or {}
    collector = MockCollector(snap or {
        "firewall": {"detections_1m": 0},
        "system": {"error_rate_1m": 0.0, "requests_1m": 0},
        "guardrail": {"violations_1m": 0},
        "forensics": {"active_sessions": 0},
    })
    return IncidentDetector(collector, check_interval=999)   # long interval so loop doesn't run


# ── Test 1: check_anomalies detects FIREWALL_BURST ────────────────────────────

async def test_incident_detector_firewall_burst():
    from ironcore.monitoring.incident_detector import AnomalyType
    detector = _make_detector({
        "firewall": {"detections_1m": 15},          # > threshold of 10
        "system": {"error_rate_1m": 0.0, "requests_1m": 0},
        "guardrail": {"violations_1m": 0},
        "forensics": {"active_sessions": 0},
    })
    incidents = await detector.check_anomalies()
    types = [i.anomaly_type for i in incidents]
    assert AnomalyType.FIREWALL_BURST in types
    assert incidents[0].severity in ("high", "critical")


# ── Test 2: cooldown prevents re-firing ──────────────────────────────────────

async def test_incident_detector_cooldown():
    from ironcore.monitoring.incident_detector import AnomalyType
    detector = _make_detector({
        "firewall": {"detections_1m": 15},
        "system": {"error_rate_1m": 0.0, "requests_1m": 0},
        "guardrail": {"violations_1m": 0},
        "forensics": {"active_sessions": 0},
    })
    first = await detector.check_anomalies()
    second = await detector.check_anomalies()   # should be empty (in cooldown)
    fw_first = [i for i in first if i.anomaly_type == AnomalyType.FIREWALL_BURST]
    fw_second = [i for i in second if i.anomaly_type == AnomalyType.FIREWALL_BURST]
    assert len(fw_first) == 1
    assert len(fw_second) == 0   # cooldown


# ── Test 3: list_active_incidents returns only active ─────────────────────────

async def test_incident_detector_list_active():
    from ironcore.monitoring.incident_detector import AnomalyType
    detector = _make_detector({
        "firewall": {"detections_1m": 15},
        "system": {"error_rate_1m": 0.0, "requests_1m": 0},
        "guardrail": {"violations_1m": 0},
        "forensics": {"active_sessions": 0},
    })
    await detector.check_anomalies()
    active = detector.list_active_incidents()
    assert len(active) >= 1
    assert all(i.status.value == "active" for i in active)


# ── Test 4: resolve_incident marks as resolved ────────────────────────────────

async def test_incident_detector_resolve():
    from ironcore.monitoring.incident_detector import IncidentStatus
    detector = _make_detector({
        "firewall": {"detections_1m": 15},
        "system": {"error_rate_1m": 0.0, "requests_1m": 0},
        "guardrail": {"violations_1m": 0},
        "forensics": {"active_sessions": 0},
    })
    incidents = await detector.check_anomalies()
    assert incidents
    inc_id = incidents[0].id
    ok = detector.resolve_incident(inc_id, manual=True)
    assert ok
    resolved = detector.get_incident(inc_id)
    assert resolved.status == IncidentStatus.MANUALLY_RESOLVED


# ── Test 5: HIGH_ERROR_RATE detection ────────────────────────────────────────

async def test_incident_detector_high_error_rate():
    from ironcore.monitoring.incident_detector import AnomalyType
    detector = _make_detector({
        "firewall": {"detections_1m": 0},
        "system": {"error_rate_1m": 0.8, "requests_1m": 0},  # > 0.5 threshold
        "guardrail": {"violations_1m": 0},
        "forensics": {"active_sessions": 0},
    })
    incidents = await detector.check_anomalies()
    types = [i.anomaly_type for i in incidents]
    assert AnomalyType.HIGH_ERROR_RATE in types


# ── Test 6: AlertManager default routing ─────────────────────────────────────

def test_alert_manager_default_routing():
    from ironcore.monitoring.alert_manager import AlertManager, AlertChannel
    mgr = AlertManager()
    routing = mgr.get_routing()
    assert AlertChannel.SIEM.value in routing["critical"]
    assert AlertChannel.TELEGRAM.value in routing["critical"]
    assert AlertChannel.WEBHOOK.value in routing["critical"]
    assert AlertChannel.SIEM.value in routing["high"]


# ── Test 7: configure_routing updates table ───────────────────────────────────

async def test_alert_manager_configure_routing():
    from ironcore.monitoring.alert_manager import AlertManager, AlertChannel
    mgr = AlertManager()
    await mgr.configure_routing("low", [AlertChannel.SIEM])
    routing = mgr.get_routing()
    assert routing["low"] == ["siem"]


# ── Test 8: send_alert dispatches to SIEM ────────────────────────────────────

async def test_alert_manager_siem_dispatch(monkeypatch):
    from ironcore.monitoring.alert_manager import AlertManager, AlertChannel
    from ironcore.monitoring.incident_detector import AnomalyType, Incident
    recorded = []
    monkeypatch.setattr(
        "ironcore.api.siem_routes.record_event",
        lambda ev: recorded.append(ev),
    )
    mgr = AlertManager()
    inc = Incident(
        anomaly_type=AnomalyType.FIREWALL_BURST,
        severity="high",
        context={"firewall_detections_1m": 15},
        suggested_actions=["action1"],
    )
    await mgr.send_alert(inc, channels=[AlertChannel.SIEM])
    assert len(recorded) == 1
    assert "firewall_burst" in recorded[0]["event_type"]


# ── Test 9: register_playbook stores playbook ─────────────────────────────────

async def test_automation_register_playbook():
    from ironcore.monitoring.automation_layer import AutomationLayer, Playbook, PlaybookStep, AnomalyType
    layer = AutomationLayer()
    pb = Playbook(
        name="Test PB",
        trigger=AnomalyType.FIREWALL_BURST,
        steps=[PlaybookStep(action="notify_hitl", params={"priority": "high"})],
    )
    await layer.register_playbook(pb)
    playbooks = layer.list_playbooks()
    assert any(p.name == "Test PB" for p in playbooks)


# ── Test 10: execute_playbook runs all steps ──────────────────────────────────

async def test_automation_execute_playbook():
    from ironcore.monitoring.automation_layer import AutomationLayer, Playbook, PlaybookStep
    from ironcore.monitoring.incident_detector import AnomalyType, Incident
    layer = AutomationLayer()
    pb = Playbook(
        name="Firewall PB",
        trigger=AnomalyType.FIREWALL_BURST,
        steps=[
            PlaybookStep(action="notify_hitl", params={"priority": "high"}),
            PlaybookStep(action="throttle_session", params={"rate": 5}),
        ],
    )
    await layer.register_playbook(pb)
    incident = Incident(
        anomaly_type=AnomalyType.FIREWALL_BURST, severity="high",
        context={}, suggested_actions=[],
    )
    result = await layer.execute_playbook(incident)
    assert result.steps_executed == 2
    assert result.success


# ── Test 11: notify_hitl step returns hitl_request_id ────────────────────────

async def test_automation_notify_hitl_step():
    from ironcore.monitoring.automation_layer import AutomationLayer, Playbook, PlaybookStep
    from ironcore.monitoring.incident_detector import AnomalyType, Incident
    layer = AutomationLayer()
    pb = Playbook(
        name="HITL PB", trigger=AnomalyType.GUARDRAIL_BURST,
        steps=[PlaybookStep(action="notify_hitl", params={"priority": "critical"})],
    )
    await layer.register_playbook(pb)
    incident = Incident(
        anomaly_type=AnomalyType.GUARDRAIL_BURST, severity="medium",
        context={}, suggested_actions=[],
    )
    result = await layer.execute_playbook(incident)
    step_result = result.step_results[0]
    assert step_result["success"]
    assert "hitl_request_id" in step_result


# ── Test 12: no matching playbook returns success with error note ─────────────

async def test_automation_no_matching_playbook():
    from ironcore.monitoring.automation_layer import AutomationLayer
    from ironcore.monitoring.incident_detector import AnomalyType, Incident
    layer = AutomationLayer()    # empty — no playbooks registered
    incident = Incident(
        anomaly_type=AnomalyType.SESSION_ANOMALY, severity="medium",
        context={}, suggested_actions=[],
    )
    result = await layer.execute_playbook(incident)
    assert result.success   # no-op is success
    assert "No matching playbook" in (result.error or "")


# ── Test 13: PolicyLearner detects APPROVE pattern → ALLOW suggestion ─────────

async def test_policy_learner_approve_pattern():
    from ironcore.monitoring.automation_layer import PolicyLearner
    learner = PolicyLearner()
    decisions = [
        {"action_type": "exec_shell", "action": "approved", "timestamp": time.time() - i * 3600}
        for i in range(5)   # 5 approvals → > threshold of 3
    ]
    learner.ingest_hitl_decisions(decisions)
    suggestions = await learner.analyze_decisions(window_days=7)
    allow_suggestions = [s for s in suggestions if s.action_type == "exec_shell" and s.suggested_effect == "allow"]
    assert len(allow_suggestions) == 1
    assert allow_suggestions[0].confidence > 0.0


# ── Test 14: PolicyLearner detects REJECT pattern → BLOCK suggestion ──────────

async def test_policy_learner_reject_pattern():
    from ironcore.monitoring.automation_layer import PolicyLearner
    learner = PolicyLearner()
    decisions = [
        {"action_type": "delete_file", "action": "rejected", "timestamp": time.time() - i * 3600}
        for i in range(4)   # 4 rejections → > threshold of 3
    ]
    learner.ingest_hitl_decisions(decisions)
    suggestions = await learner.analyze_decisions(window_days=7)
    block_suggestions = [s for s in suggestions if s.action_type == "delete_file" and s.suggested_effect == "block"]
    assert len(block_suggestions) == 1


# ── Test 15: approve_suggestion changes status ────────────────────────────────

async def test_policy_learner_approve_suggestion():
    from ironcore.monitoring.automation_layer import PolicyLearner
    learner = PolicyLearner()
    decisions = [
        {"action_type": "write_code", "action": "approved", "timestamp": time.time() - i * 3600}
        for i in range(3)
    ]
    learner.ingest_hitl_decisions(decisions)
    suggestions = await learner.analyze_decisions(window_days=7)
    assert suggestions
    sid = suggestions[0].id
    updated = await learner.approve_suggestion(sid)
    assert updated.status == "approved"
    # Should no longer appear in pending
    pending = await learner.get_suggestions()
    assert not any(s.id == sid for s in pending)
