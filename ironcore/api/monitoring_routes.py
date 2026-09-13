"""
Monitoring API Routes — Phase 4, Security V3.

Endpoints consumed by ChatGPT UI V3 (Security Dashboard):

  GET  /api/monitoring/metrics                  → current snapshot (JSON)
  GET  /api/monitoring/metrics/stream           → SSE live metrics feed (every 5s)
  GET  /api/monitoring/alerts                   → list fired alerts
  POST /api/monitoring/alerts/{id}/resolve      → resolve an alert
  GET  /api/monitoring/alert-rules              → list alert rules
  POST /api/monitoring/alert-rules              → create alert rule
  PUT  /api/monitoring/alert-rules/{id}         → update alert rule
  DELETE /api/monitoring/alert-rules/{id}       → delete alert rule
  POST /api/monitoring/alert-rules/{id}/enable  → toggle enabled
  GET  /api/monitoring/alert-rules/{id}/test    → dry-run rule against current metrics

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ironcore.enterprise.monitoring.alert_engine import AlertEngine, AlertRule, AlertSeverity
from ironcore.enterprise.monitoring.metrics_collector import MetricsCollector

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Monitoring"])

# Module-level singletons — inject via set_monitoring()
_collector: Optional[MetricsCollector] = None
_alert_engine: Optional[AlertEngine] = None


def set_monitoring(collector: MetricsCollector, alert_engine: AlertEngine) -> None:
    """Called at server startup to inject shared monitoring singletons."""
    global _collector, _alert_engine
    _collector = collector
    _alert_engine = alert_engine
    logger.info("[MonitoringRoutes] MetricsCollector + AlertEngine registered.")


def _get_collector() -> MetricsCollector:
    if _collector is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Monitoring not initialized")
    return _collector


def _get_engine() -> AlertEngine:
    if _alert_engine is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AlertEngine not initialized")
    return _alert_engine


# ── Request models ─────────────────────────────────────────────────────────────

class CreateAlertRuleRequest(BaseModel):
    name: str
    description: str = ""
    metric_path: str
    operator: str = ">"
    threshold: float
    severity: str = "warning"
    cooldown_seconds: int = 300
    channels: List[str] = ["log"]
    enabled: bool = True


class UpdateAlertRuleRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    metric_path: Optional[str] = None
    operator: Optional[str] = None
    threshold: Optional[float] = None
    severity: Optional[str] = None
    cooldown_seconds: Optional[int] = None
    channels: Optional[List[str]] = None
    enabled: Optional[bool] = None


# ── Metrics endpoints ──────────────────────────────────────────────────────────

@router.get("/metrics")
async def get_metrics_snapshot() -> Dict[str, Any]:
    """
    GET /api/monitoring/metrics

    Return current live metrics snapshot (all modules).
    """
    collector = _get_collector()
    return collector.snapshot()


@router.get("/metrics/stream")
async def stream_metrics_sse(
    interval: float = Query(5.0, ge=1.0, le=60.0),
) -> StreamingResponse:
    """
    GET /api/monitoring/metrics/stream?interval=5

    Server-Sent Events: push metrics snapshot every N seconds.
    Also interleaves recent fired alerts.
    Used by the ChatGPT UI V3 Security Dashboard real-time charts.
    """
    collector = _get_collector()
    engine = _get_engine()

    async def _stream():
        seen_alert_ids = set()
        while True:
            snap = collector.snapshot()
            recent = engine.get_recent_alerts()

            # Emit metrics
            yield f"data: {json.dumps({'type': 'metrics', 'data': snap})}\n\n"

            # Emit any new alerts since last tick
            for alert in recent:
                if alert.alert_id not in seen_alert_ids:
                    seen_alert_ids.add(alert.alert_id)
                    yield f"data: {json.dumps({'type': 'alert', 'data': alert.model_dump()})}\n\n"

            await asyncio.sleep(interval)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Fired alerts ───────────────────────────────────────────────────────────────

@router.get("/alerts")
async def list_fired_alerts(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> List[Dict[str, Any]]:
    """
    GET /api/monitoring/alerts?status=active

    List fired alerts, optionally filtered by status (active|resolved|muted).
    """
    engine = _get_engine()
    alerts = await engine.list_fired_alerts(status=status_filter, limit=limit)
    return [a.model_dump() for a in alerts]


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str) -> Dict[str, Any]:
    """
    POST /api/monitoring/alerts/{alert_id}/resolve

    Mark a fired alert as resolved.
    """
    engine = _get_engine()
    ok = await engine.resolve_alert(alert_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Alert '{alert_id}' not found")
    return {"alert_id": alert_id, "status": "resolved", "resolved_at": time.time()}


# ── Alert rules CRUD ───────────────────────────────────────────────────────────

@router.get("/alert-rules")
async def list_alert_rules() -> List[Dict[str, Any]]:
    """List all alert rules."""
    engine = _get_engine()
    rules = await engine.list_rules()
    return [r.model_dump() for r in rules]


@router.post("/alert-rules", status_code=status.HTTP_201_CREATED)
async def create_alert_rule(body: CreateAlertRuleRequest) -> Dict[str, Any]:
    """Create a new alert rule."""
    engine = _get_engine()
    try:
        rule = AlertRule(
            name=body.name,
            description=body.description,
            metric_path=body.metric_path,
            operator=body.operator,
            threshold=body.threshold,
            severity=AlertSeverity(body.severity),
            cooldown_seconds=body.cooldown_seconds,
            channels=body.channels,
            enabled=body.enabled,
        )
        saved = await engine.add_rule(rule)
        return saved.model_dump()
    except (ValueError, KeyError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.get("/alert-rules/{rule_id}")
async def get_alert_rule(rule_id: str) -> Dict[str, Any]:
    engine = _get_engine()
    rule = await engine.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rule '{rule_id}' not found")
    return rule.model_dump()


@router.put("/alert-rules/{rule_id}")
async def update_alert_rule(rule_id: str, body: UpdateAlertRuleRequest) -> Dict[str, Any]:
    """Partial update of an alert rule."""
    engine = _get_engine()
    existing = await engine.get_rule(rule_id)
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rule '{rule_id}' not found")

    updates: Dict[str, Any] = {}
    if body.name is not None:          updates["name"] = body.name
    if body.description is not None:   updates["description"] = body.description
    if body.metric_path is not None:   updates["metric_path"] = body.metric_path
    if body.operator is not None:      updates["operator"] = body.operator
    if body.threshold is not None:     updates["threshold"] = body.threshold
    if body.severity is not None:      updates["severity"] = AlertSeverity(body.severity)
    if body.cooldown_seconds is not None: updates["cooldown_seconds"] = body.cooldown_seconds
    if body.channels is not None:      updates["channels"] = body.channels
    if body.enabled is not None:       updates["enabled"] = body.enabled

    updated = existing.model_copy(update=updates)
    try:
        saved = await engine.add_rule(updated)
        return saved.model_dump()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.delete("/alert-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(rule_id: str) -> None:
    engine = _get_engine()
    deleted = await engine.delete_rule(rule_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rule '{rule_id}' not found")


@router.post("/alert-rules/{rule_id}/enable")
async def toggle_alert_rule(
    rule_id: str,
    enabled: bool = Query(True),
) -> Dict[str, Any]:
    engine = _get_engine()
    ok = await engine.enable_rule(rule_id, enabled)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rule '{rule_id}' not found")
    return {"rule_id": rule_id, "enabled": enabled}


@router.get("/alert-rules/{rule_id}/test")
async def test_alert_rule(rule_id: str) -> Dict[str, Any]:
    """
    GET /api/monitoring/alert-rules/{rule_id}/test

    Dry-run the alert rule against the current live metrics snapshot.
    Returns whether it WOULD fire, with the current metric value.
    """
    engine = _get_engine()
    collector = _get_collector()

    rule = await engine.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rule '{rule_id}' not found")

    from ironcore.enterprise.monitoring.alert_engine import _OPS, _get_nested
    snap = collector.snapshot()
    value = _get_nested(snap, rule.metric_path)

    if value is None:
        return {
            "rule_id": rule_id,
            "metric_path": rule.metric_path,
            "current_value": None,
            "threshold": rule.threshold,
            "would_fire": False,
            "reason": f"metric path '{rule.metric_path}' not found in snapshot",
        }

    op_fn = _OPS.get(rule.operator)
    would_fire = op_fn(value, rule.threshold) if op_fn else False
    return {
        "rule_id": rule_id,
        "metric_path": rule.metric_path,
        "current_value": value,
        "threshold": rule.threshold,
        "operator": rule.operator,
        "would_fire": would_fire,
        "severity": rule.severity.value,
    }
