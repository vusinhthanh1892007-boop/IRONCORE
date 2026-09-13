"""
Tests — Phase 4: Security V3 — Monitoring & Alerting.

Coverage:
  1.  metrics_collector: sliding counter increment + total
  2.  metrics_collector: count_in_window returns correct count
  3.  metrics_collector: rate() returns float
  4.  metrics_collector: MetricSeries records and returns points
  5.  metrics_collector: firewall.detect() → category_counts updated
  6.  metrics_collector: snapshot() returns all expected top-level keys
  7.  alert_engine: add_rule persists correctly
  8.  alert_engine: list_rules returns saved rules
  9.  alert_engine: delete_rule removes entry
  10. alert_engine: enable_rule toggles correctly
  11. alert_engine: _evaluate_all fires alert when condition met
  12. alert_engine: cooldown suppresses second alert within window
  13. alert_engine: _evaluate_all does NOT fire when condition not met
  14. alert_engine: _get_nested resolves dot-notation path correctly
  15. alert_engine: resolve_alert updates status in DB
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Dict, Any

import pytest


# ── Test 1: SlidingCounter increment + total ─────────────────────────────────

async def test_sliding_counter_increment():
    from ironcore.enterprise.monitoring.metrics_collector import SlidingCounter
    sc = SlidingCounter()
    await sc.increment(3)
    assert sc.total == 3
    await sc.increment(2)
    assert sc.total == 5


# ── Test 2: count_in_window ───────────────────────────────────────────────────

async def test_count_in_window():
    from ironcore.enterprise.monitoring.metrics_collector import SlidingCounter
    sc = SlidingCounter()
    await sc.increment(5)
    # All 5 events are within the last 60 seconds
    assert sc.count_in_window(60) == 5
    # 0 events in the last 0 seconds (edge: cutoff == now)
    assert sc.count_in_window(0) == 0


# ── Test 3: rate() returns float ──────────────────────────────────────────────

async def test_sliding_counter_rate():
    from ironcore.enterprise.monitoring.metrics_collector import SlidingCounter
    sc = SlidingCounter()
    await sc.increment(60)
    rate = sc.rate(60)
    assert isinstance(rate, float)
    assert rate >= 0.0


# ── Test 4: MetricSeries records points ───────────────────────────────────────

def test_metric_series_records():
    from ironcore.enterprise.monitoring.metrics_collector import MetricSeries
    ms = MetricSeries("test_metric")
    ms.record(10.0)
    ms.record(20.0)
    points = ms.to_list()
    assert len(points) == 2
    assert points[-1]["v"] == pytest.approx(20.0)
    assert ms.latest() == pytest.approx(20.0)


# ── Test 5: firewall.detect() updates category_counts ────────────────────────

async def test_firewall_metrics_detect():
    from ironcore.enterprise.monitoring.metrics_collector import MetricsCollector
    mc = MetricsCollector()
    await mc.firewall.detect(category="jailbreak")
    await mc.firewall.detect(category="jailbreak")
    await mc.firewall.detect(category="injection")
    assert mc.firewall.category_counts["jailbreak"] == 2
    assert mc.firewall.category_counts["injection"] == 1
    assert mc.firewall.detections.total == 3


# ── Test 6: snapshot() has all expected keys ──────────────────────────────────

async def test_snapshot_structure():
    from ironcore.enterprise.monitoring.metrics_collector import MetricsCollector
    mc = MetricsCollector()
    snap = mc.snapshot()
    assert "firewall" in snap
    assert "guardrail" in snap
    assert "forensics" in snap
    assert "system" in snap
    assert "timestamp" in snap
    assert "total_detections" in snap["firewall"]
    assert snap["firewall"]["total_detections"] == 0


# ── Test 7: add_rule persists ─────────────────────────────────────────────────

async def test_add_alert_rule_persists(tmp_path: Path):
    from ironcore.enterprise.monitoring.metrics_collector import MetricsCollector
    from ironcore.enterprise.monitoring.alert_engine import AlertEngine, AlertRule, AlertSeverity
    mc = MetricsCollector()
    engine = AlertEngine(mc, db_path=tmp_path / "alerts.db", eval_interval=999)
    await engine.initialize()
    rule = AlertRule(
        name="Test Alert",
        metric_path="firewall.blocks_1m",
        operator=">",
        threshold=5.0,
        severity=AlertSeverity.WARNING,
    )
    saved = await engine.add_rule(rule)
    assert saved.rule_id == rule.rule_id
    fetched = await engine.get_rule(rule.rule_id)
    assert fetched is not None
    assert fetched.name == "Test Alert"


# ── Test 8: list_rules returns all ───────────────────────────────────────────

async def test_list_alert_rules(tmp_path: Path):
    from ironcore.enterprise.monitoring.metrics_collector import MetricsCollector
    from ironcore.enterprise.monitoring.alert_engine import AlertEngine, AlertRule
    mc = MetricsCollector()
    engine = AlertEngine(mc, db_path=tmp_path / "alerts.db")
    await engine.initialize()
    await engine.add_rule(AlertRule(name="R1", metric_path="firewall.blocks_1m", operator=">", threshold=1))
    await engine.add_rule(AlertRule(name="R2", metric_path="guardrail.violations_1m", operator=">", threshold=2))
    rules = await engine.list_rules()
    names = {r.name for r in rules}
    assert "R1" in names
    assert "R2" in names


# ── Test 9: delete_rule ───────────────────────────────────────────────────────

async def test_delete_alert_rule(tmp_path: Path):
    from ironcore.enterprise.monitoring.metrics_collector import MetricsCollector
    from ironcore.enterprise.monitoring.alert_engine import AlertEngine, AlertRule
    mc = MetricsCollector()
    engine = AlertEngine(mc, db_path=tmp_path / "alerts.db")
    await engine.initialize()
    rule = AlertRule(name="Del", metric_path="system.errors_1m", operator=">", threshold=1)
    await engine.add_rule(rule)
    deleted = await engine.delete_rule(rule.rule_id)
    assert deleted is True
    assert await engine.get_rule(rule.rule_id) is None
    assert await engine.delete_rule("nonexistent") is False


# ── Test 10: enable_rule toggles ─────────────────────────────────────────────

async def test_enable_alert_rule(tmp_path: Path):
    from ironcore.enterprise.monitoring.metrics_collector import MetricsCollector
    from ironcore.enterprise.monitoring.alert_engine import AlertEngine, AlertRule
    mc = MetricsCollector()
    engine = AlertEngine(mc, db_path=tmp_path / "alerts.db")
    await engine.initialize()
    rule = AlertRule(name="Toggle", metric_path="firewall.blocks_1m", operator=">", threshold=1)
    await engine.add_rule(rule)
    ok = await engine.enable_rule(rule.rule_id, False)
    assert ok is True
    fetched = await engine.get_rule(rule.rule_id)
    assert fetched.enabled is False


# ── Test 11: _evaluate_all fires alert when condition met ─────────────────────

async def test_evaluate_all_fires_alert(tmp_path: Path):
    from ironcore.enterprise.monitoring.metrics_collector import MetricsCollector
    from ironcore.enterprise.monitoring.alert_engine import AlertEngine, AlertRule
    mc = MetricsCollector()
    # Simulate 10 blocks in the last minute
    for _ in range(10):
        await mc.firewall.block()
    engine = AlertEngine(mc, db_path=tmp_path / "alerts.db", eval_interval=999)
    await engine.initialize()
    # Rule: fire if blocks_1m > 5
    rule = AlertRule(
        name="Block Alert",
        metric_path="firewall.blocks_1m",
        operator=">",
        threshold=5.0,
        cooldown_seconds=0,   # no cooldown for test
    )
    await engine.add_rule(rule)
    await engine._evaluate_all()
    # Should have fired
    assert len(engine.get_recent_alerts()) == 1
    assert engine.get_recent_alerts()[0].rule_name == "Block Alert"


# ── Test 12: cooldown suppresses second alert ─────────────────────────────────

async def test_cooldown_suppresses(tmp_path: Path):
    from ironcore.enterprise.monitoring.metrics_collector import MetricsCollector
    from ironcore.enterprise.monitoring.alert_engine import AlertEngine, AlertRule
    mc = MetricsCollector()
    for _ in range(10):
        await mc.firewall.block()
    engine = AlertEngine(mc, db_path=tmp_path / "alerts.db", eval_interval=999)
    await engine.initialize()
    rule = AlertRule(
        name="Cooldown Test",
        metric_path="firewall.blocks_1m",
        operator=">",
        threshold=5.0,
        cooldown_seconds=3600,  # 1-hour cooldown
    )
    await engine.add_rule(rule)
    await engine._evaluate_all()
    count_after_first = len(engine.get_recent_alerts())
    # Second evaluation — should be suppressed by cooldown
    await engine._evaluate_all()
    count_after_second = len(engine.get_recent_alerts())
    assert count_after_first == 1
    assert count_after_second == 1   # still just 1 — cooldown worked


# ── Test 13: _evaluate_all does NOT fire when condition not met ───────────────

async def test_no_alert_when_condition_not_met(tmp_path: Path):
    from ironcore.enterprise.monitoring.metrics_collector import MetricsCollector
    from ironcore.enterprise.monitoring.alert_engine import AlertEngine, AlertRule
    mc = MetricsCollector()   # 0 blocks
    engine = AlertEngine(mc, db_path=tmp_path / "alerts.db", eval_interval=999)
    await engine.initialize()
    rule = AlertRule(
        name="No Fire",
        metric_path="firewall.blocks_1m",
        operator=">",
        threshold=100.0,
        cooldown_seconds=0,
    )
    await engine.add_rule(rule)
    await engine._evaluate_all()
    assert len(engine.get_recent_alerts()) == 0


# ── Test 14: _get_nested resolves dot-path ────────────────────────────────────

def test_get_nested_resolves_path():
    from ironcore.enterprise.monitoring.alert_engine import _get_nested
    snap: Dict[str, Any] = {
        "firewall": {"blocks_1m": 7, "total_blocks": 42},
        "system": {"error_rate_1m": 0.05},
    }
    assert _get_nested(snap, "firewall.blocks_1m") == pytest.approx(7.0)
    assert _get_nested(snap, "system.error_rate_1m") == pytest.approx(0.05)
    assert _get_nested(snap, "firewall.nonexistent") is None
    assert _get_nested(snap, "missing.path") is None


# ── Test 15: resolve_alert updates status ────────────────────────────────────

async def test_resolve_alert(tmp_path: Path):
    from ironcore.enterprise.monitoring.metrics_collector import MetricsCollector
    from ironcore.enterprise.monitoring.alert_engine import AlertEngine, AlertRule
    mc = MetricsCollector()
    for _ in range(10):
        await mc.firewall.block()
    engine = AlertEngine(mc, db_path=tmp_path / "alerts.db", eval_interval=999)
    await engine.initialize()
    rule = AlertRule(name="Resolve Test", metric_path="firewall.blocks_1m",
                     operator=">", threshold=5.0, cooldown_seconds=0)
    await engine.add_rule(rule)
    await engine._evaluate_all()
    alerts = await engine.list_fired_alerts(status="active")
    assert len(alerts) >= 1
    alert_id = alerts[0].alert_id
    ok = await engine.resolve_alert(alert_id)
    assert ok is True
    resolved = await engine.list_fired_alerts(status="resolved")
    assert any(a.alert_id == alert_id for a in resolved)
