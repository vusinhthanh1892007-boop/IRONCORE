"""
Alert Engine — Phase 4, Security V3.

Evaluates alert rules against live metrics and dispatches notifications.

Alert Rule model:
  - metric_path: dot-notation path into the snapshot dict
    Examples: "firewall.blocks_1m", "guardrail.violations_5m", "system.error_rate_1m"
  - operator: >, <, >=, <=, ==
  - threshold: numeric trigger value
  - severity: info | warning | critical
  - cooldown_seconds: minimum gap between repeated notifications for the same alert
  - channels: list of notification channels ["log", "webhook", "console"]

Dispatch channels:
  - log: Python logger (always)
  - console: print to stdout (for terminal UIs)
  - webhook: HTTP POST to a configured URL (IRONCORE_ALERT_WEBHOOK_URL)

One AlertEngine instance is created at startup and runs an evaluation loop
every IRONCORE_ALERT_EVAL_INTERVAL seconds (default: 15s).

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import asyncio
import json
import logging
import operator as _op
import os
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import aiosqlite
from pydantic import BaseModel, Field

from ironcore.enterprise.monitoring.metrics_collector import MetricsCollector

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_ALERT_DB_PATH = Path(
    os.environ.get("IRONCORE_ALERT_DB_PATH",
                   str(Path.home() / ".ironcore" / "alerts.db"))
)
_EVAL_INTERVAL = int(os.environ.get("IRONCORE_ALERT_EVAL_INTERVAL", "15"))
_WEBHOOK_URL   = os.environ.get("IRONCORE_ALERT_WEBHOOK_URL", "")

# Operator map for condition evaluation
_OPS: Dict[str, Callable[[float, float], bool]] = {
    ">":  _op.gt,
    "<":  _op.lt,
    ">=": _op.ge,
    "<=": _op.le,
    "==": _op.eq,
    "!=": _op.ne,
}


# ── Enums ─────────────────────────────────────────────────────────────────────

class AlertSeverity(str, Enum):
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    ACTIVE   = "active"
    RESOLVED = "resolved"
    MUTED    = "muted"


# ── Models ─────────────────────────────────────────────────────────────────────

class AlertRule(BaseModel):
    """One alert rule definition."""

    rule_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    metric_path: str           # e.g. "firewall.blocks_1m"
    operator: str = ">"        # >, <, >=, <=, ==, !=
    threshold: float
    severity: AlertSeverity = AlertSeverity.WARNING
    cooldown_seconds: int = 300     # 5 minutes default cooldown
    channels: List[str] = Field(default_factory=lambda: ["log"])
    enabled: bool = True
    created_at: float = Field(default_factory=time.time)

    def validate_fields(self) -> List[str]:
        errors: List[str] = []
        if not self.name.strip():
            errors.append("name must not be empty")
        if self.operator not in _OPS:
            errors.append(f"operator must be one of {list(_OPS.keys())}")
        if self.cooldown_seconds < 0:
            errors.append("cooldown_seconds must be >= 0")
        return errors


class FiredAlert(BaseModel):
    """A single fired alert event."""

    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    rule_id: str
    rule_name: str
    severity: str
    metric_path: str
    metric_value: float
    threshold: float
    operator: str
    message: str
    fired_at: float = Field(default_factory=time.time)
    status: AlertStatus = AlertStatus.ACTIVE
    resolved_at: Optional[float] = None


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS alert_rules (
    rule_id          TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    metric_path      TEXT NOT NULL,
    operator         TEXT NOT NULL,
    threshold        REAL NOT NULL,
    severity         TEXT NOT NULL,
    cooldown_seconds INTEGER NOT NULL,
    channels_json    TEXT NOT NULL,
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS fired_alerts (
    alert_id     TEXT PRIMARY KEY,
    rule_id      TEXT NOT NULL,
    rule_name    TEXT NOT NULL,
    severity     TEXT NOT NULL,
    metric_path  TEXT NOT NULL,
    metric_value REAL NOT NULL,
    threshold    REAL NOT NULL,
    operator     TEXT NOT NULL,
    message      TEXT NOT NULL,
    fired_at     REAL NOT NULL,
    status       TEXT NOT NULL DEFAULT 'active',
    resolved_at  REAL
);

CREATE INDEX IF NOT EXISTS idx_fa_status   ON fired_alerts(status);
CREATE INDEX IF NOT EXISTS idx_fa_fired_at ON fired_alerts(fired_at);
"""


# ── AlertEngine ────────────────────────────────────────────────────────────────

class AlertEngine:
    """
    Evaluates alert rules against live metrics every N seconds.

    Usage::

        engine = AlertEngine(metrics_collector)
        await engine.initialize()
        await engine.add_rule(AlertRule(
            name="High Firewall Block Rate",
            metric_path="firewall.blocks_1m",
            operator=">",
            threshold=10,
            severity=AlertSeverity.CRITICAL,
            cooldown_seconds=300,
        ))
        # Start background eval loop (call once at server startup)
        asyncio.create_task(engine.run_eval_loop())
    """

    def __init__(
        self,
        collector: MetricsCollector,
        db_path: Optional[Path] = None,
        eval_interval: int = _EVAL_INTERVAL,
    ) -> None:
        self._collector    = collector
        self._db_path      = (db_path or _ALERT_DB_PATH).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._eval_interval = eval_interval
        self._initialized  = False
        # cooldown tracking: rule_id → last_fired_timestamp
        self._last_fired: Dict[str, float] = {}
        # Recent fired alerts (in-memory ring buffer for SSE streaming)
        self._recent_alerts: List[FiredAlert] = []
        self._max_recent = 100
        self._running = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.executescript(_SCHEMA_SQL)
            await db.commit()
        self._initialized = True
        logger.info("[AlertEngine] Initialized db=%s", self._db_path)

    # ── Rule management ────────────────────────────────────────────────────────

    async def add_rule(self, rule: AlertRule) -> AlertRule:
        errs = rule.validate_fields()
        if errs:
            raise ValueError(f"Rule validation failed: {'; '.join(errs)}")
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO alert_rules
                (rule_id, name, description, metric_path, operator, threshold,
                 severity, cooldown_seconds, channels_json, enabled, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    rule.rule_id, rule.name, rule.description,
                    rule.metric_path, rule.operator, rule.threshold,
                    rule.severity.value, rule.cooldown_seconds,
                    json.dumps(rule.channels),
                    int(rule.enabled), rule.created_at,
                ),
            )
            await db.commit()
        logger.info("[AlertEngine] Rule added: %s", rule.name)
        return rule

    async def list_rules(self) -> List[AlertRule]:
        async with aiosqlite.connect(str(self._db_path)) as db:
            async with db.execute(
                "SELECT rule_id, name, description, metric_path, operator, threshold, "
                "severity, cooldown_seconds, channels_json, enabled, created_at "
                "FROM alert_rules ORDER BY created_at DESC"
            ) as cur:
                rows = await cur.fetchall()
        return [self._row_to_rule(r) for r in rows]

    async def get_rule(self, rule_id: str) -> Optional[AlertRule]:
        async with aiosqlite.connect(str(self._db_path)) as db:
            async with db.execute(
                "SELECT rule_id, name, description, metric_path, operator, threshold, "
                "severity, cooldown_seconds, channels_json, enabled, created_at "
                "FROM alert_rules WHERE rule_id=?", (rule_id,)
            ) as cur:
                row = await cur.fetchone()
        return self._row_to_rule(row) if row else None

    async def delete_rule(self, rule_id: str) -> bool:
        async with aiosqlite.connect(str(self._db_path)) as db:
            cur = await db.execute("DELETE FROM alert_rules WHERE rule_id=?", (rule_id,))
            deleted = cur.rowcount > 0
            await db.commit()
        return deleted

    async def enable_rule(self, rule_id: str, enabled: bool) -> bool:
        async with aiosqlite.connect(str(self._db_path)) as db:
            cur = await db.execute(
                "UPDATE alert_rules SET enabled=? WHERE rule_id=?", (int(enabled), rule_id)
            )
            ok = cur.rowcount > 0
            await db.commit()
        return ok

    # ── Fired alerts ───────────────────────────────────────────────────────────

    async def list_fired_alerts(
        self,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[FiredAlert]:
        conditions = []
        params: List[Any] = []
        if status:
            conditions.append("status=?")
            params.append(status)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        async with aiosqlite.connect(str(self._db_path)) as db:
            async with db.execute(
                f"SELECT alert_id, rule_id, rule_name, severity, metric_path, "
                f"metric_value, threshold, operator, message, fired_at, status, resolved_at "
                f"FROM fired_alerts {where} ORDER BY fired_at DESC LIMIT ?",
                params,
            ) as cur:
                rows = await cur.fetchall()
        return [self._row_to_alert(r) for r in rows]

    def get_recent_alerts(self) -> List[FiredAlert]:
        """Return in-memory recent alerts (fast, no DB)."""
        return list(self._recent_alerts)

    async def resolve_alert(self, alert_id: str) -> bool:
        async with aiosqlite.connect(str(self._db_path)) as db:
            cur = await db.execute(
                "UPDATE fired_alerts SET status='resolved', resolved_at=? WHERE alert_id=?",
                (time.time(), alert_id),
            )
            ok = cur.rowcount > 0
            await db.commit()
        return ok

    # ── Evaluation loop ────────────────────────────────────────────────────────

    async def run_eval_loop(self) -> None:
        """Background task: evaluate all rules every N seconds."""
        self._running = True
        logger.info("[AlertEngine] Evaluation loop started (interval=%ds)", self._eval_interval)
        while self._running:
            try:
                await self._evaluate_all()
                await self._collector.save_snapshot()
            except Exception as exc:  # noqa: BLE001
                logger.error("[AlertEngine] Eval loop error: %s", exc)
            await asyncio.sleep(self._eval_interval)

    def stop(self) -> None:
        self._running = False

    async def _evaluate_all(self) -> None:
        """Evaluate all enabled rules against current metrics snapshot."""
        snapshot = self._collector.snapshot()
        rules = await self.list_rules()
        enabled_rules = [r for r in rules if r.enabled]

        for rule in enabled_rules:
            value = _get_nested(snapshot, rule.metric_path)
            if value is None:
                continue

            op_fn = _OPS.get(rule.operator)
            if op_fn is None:
                continue

            if op_fn(float(value), rule.threshold):
                await self._fire_alert(rule, float(value))

    async def _fire_alert(self, rule: AlertRule, value: float) -> None:
        """Fire an alert if not in cooldown window."""
        now = time.time()
        last = self._last_fired.get(rule.rule_id, 0)
        if now - last < rule.cooldown_seconds:
            logger.debug(
                "[AlertEngine] Alert '%s' in cooldown (%.0fs remaining)",
                rule.name, rule.cooldown_seconds - (now - last),
            )
            return

        self._last_fired[rule.rule_id] = now
        message = (
            f"[{rule.severity.upper()}] {rule.name}: "
            f"{rule.metric_path} {rule.operator} {rule.threshold} "
            f"(current: {value:.2f})"
        )

        alert = FiredAlert(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            severity=rule.severity.value,
            metric_path=rule.metric_path,
            metric_value=value,
            threshold=rule.threshold,
            operator=rule.operator,
            message=message,
        )

        # Persist to DB
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                "INSERT INTO fired_alerts "
                "(alert_id, rule_id, rule_name, severity, metric_path, metric_value, "
                "threshold, operator, message, fired_at, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    alert.alert_id, alert.rule_id, alert.rule_name,
                    alert.severity, alert.metric_path, alert.metric_value,
                    alert.threshold, alert.operator, alert.message,
                    alert.fired_at, alert.status.value,
                ),
            )
            await db.commit()

        # Add to in-memory ring buffer
        self._recent_alerts.append(alert)
        if len(self._recent_alerts) > self._max_recent:
            self._recent_alerts.pop(0)

        # Dispatch notifications
        await self._dispatch(alert, rule.channels)

    async def _dispatch(self, alert: FiredAlert, channels: List[str]) -> None:
        """Send alert notification to all configured channels."""
        # Always log
        log_fn = {"info": logger.info, "warning": logger.warning, "critical": logger.critical}.get(
            alert.severity, logger.warning
        )
        log_fn("[AlertEngine] ALERT FIRED: %s", alert.message)

        if "console" in channels:
            print(f"\n🚨 ALERT [{alert.severity.upper()}] {alert.message}\n")

        if "webhook" in channels and _WEBHOOK_URL:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    await session.post(
                        _WEBHOOK_URL,
                        json=alert.model_dump(),
                        timeout=aiohttp.ClientTimeout(total=5),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[AlertEngine] Webhook dispatch failed: %s", exc)

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_rule(row: tuple) -> AlertRule:
        (rule_id, name, description, metric_path, operator, threshold,
         severity, cooldown_seconds, channels_json, enabled, created_at) = row
        return AlertRule(
            rule_id=rule_id,
            name=name,
            description=description,
            metric_path=metric_path,
            operator=operator,
            threshold=float(threshold),
            severity=AlertSeverity(severity),
            cooldown_seconds=cooldown_seconds,
            channels=json.loads(channels_json),
            enabled=bool(enabled),
            created_at=created_at,
        )

    @staticmethod
    def _row_to_alert(row: tuple) -> FiredAlert:
        (alert_id, rule_id, rule_name, severity, metric_path, metric_value,
         threshold, operator, message, fired_at, status, resolved_at) = row
        return FiredAlert(
            alert_id=alert_id,
            rule_id=rule_id,
            rule_name=rule_name,
            severity=severity,
            metric_path=metric_path,
            metric_value=metric_value,
            threshold=float(threshold),
            operator=operator,
            message=message,
            fired_at=fired_at,
            status=AlertStatus(status),
            resolved_at=resolved_at,
        )


# ── Utility ────────────────────────────────────────────────────────────────────

def _get_nested(d: Dict[str, Any], path: str) -> Optional[float]:
    """
    Resolve a dot-notation path in a nested dict.
    Example: _get_nested(snap, "firewall.blocks_1m") → float or None
    """
    parts = path.split(".")
    current: Any = d
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    if current is None:
        return None
    try:
        return float(current)
    except (TypeError, ValueError):
        return None
