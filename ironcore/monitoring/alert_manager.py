"""
Alert Manager — Phase 6, Security V3 (Section 21: Automation & Intelligence).

Multi-channel alert dispatcher. Routes incidents to appropriate channels based
on severity:

  critical → SIEM + Telegram + Webhook
  high     → SIEM + Webhook
  medium   → SIEM
  low      → log only

Channels:
  - SIEM:     Pushes to the SIEM event ring buffer (ironcore/api/siem_routes.py)
  - Webhook:  HTTP POST to configured URL (IRONCORE_ALERT_WEBHOOK_URL)
  - Telegram: Bot API message (IRONCORE_TELEGRAM_BOT_TOKEN + IRONCORE_TELEGRAM_CHAT_ID)
  - Email:    SMTP send (IRONCORE_SMTP_HOST/PORT/FROM/TO)

All channels are fire-and-forget with exception isolation.

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import logging
import os
import time
from enum import Enum
from typing import Any, Dict, List, Optional

from ironcore.monitoring.incident_detector import Incident

logger = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────

class AlertChannel(str, Enum):
    SIEM     = "siem"
    WEBHOOK  = "webhook"
    TELEGRAM = "telegram"
    EMAIL    = "email"


# ── Default routing table ──────────────────────────────────────────────────────

_DEFAULT_ROUTING: Dict[str, List[AlertChannel]] = {
    "critical": [AlertChannel.SIEM, AlertChannel.TELEGRAM, AlertChannel.WEBHOOK],
    "high":     [AlertChannel.SIEM, AlertChannel.WEBHOOK],
    "medium":   [AlertChannel.SIEM],
    "low":      [],   # log only
    "unknown":  [AlertChannel.SIEM],
}


# ── AlertManager ───────────────────────────────────────────────────────────────

class AlertManager:
    """
    Routes incidents to notification channels based on severity.

    Usage::

        manager = AlertManager()
        await manager.send_alert(incident)   # uses default routing
        await manager.configure_routing("low", [AlertChannel.SIEM])  # override
    """

    def __init__(self) -> None:
        self._routing: Dict[str, List[AlertChannel]] = dict(_DEFAULT_ROUTING)
        self._sent_count: int = 0
        self._failed_count: int = 0

    async def send_alert(
        self,
        incident: Incident,
        channels: Optional[List[AlertChannel]] = None,
    ) -> None:
        """
        Send alert for an incident to all appropriate channels.
        If channels is None, uses configured routing table for incident.severity.
        """
        resolved_channels = channels or self._routing.get(incident.severity, [AlertChannel.SIEM])
        logger.warning(
            "[AlertManager] ALERT: type=%s severity=%s channels=%s",
            incident.anomaly_type, incident.severity,
            [c.value for c in resolved_channels],
        )

        for channel in resolved_channels:
            try:
                if channel == AlertChannel.SIEM:
                    await self._dispatch_siem(incident)
                elif channel == AlertChannel.WEBHOOK:
                    await self._dispatch_webhook(incident)
                elif channel == AlertChannel.TELEGRAM:
                    await self._dispatch_telegram(incident)
                elif channel == AlertChannel.EMAIL:
                    await self._dispatch_email(incident)
                self._sent_count += 1
            except Exception as exc:  # noqa: BLE001
                self._failed_count += 1
                logger.warning("[AlertManager] Channel %s failed: %s", channel, exc)

    async def configure_routing(
        self,
        severity: str,
        channels: List[AlertChannel],
    ) -> None:
        """Override the default routing for a given severity level."""
        self._routing[severity] = list(channels)
        logger.info("[AlertManager] Routing updated: %s → %s", severity, [c.value for c in channels])

    def get_routing(self) -> Dict[str, List[str]]:
        """Return current routing table as plain-string dict for API serialization."""
        return {sev: [c.value for c in chans] for sev, chans in self._routing.items()}

    # ── Channel dispatchers ────────────────────────────────────────────────────

    async def _dispatch_siem(self, incident: Incident) -> None:
        """Push incident to the SIEM event ring buffer."""
        try:
            from ironcore.api.siem_routes import record_event
            record_event({
                "event_type": f"incident_{incident.anomaly_type.value}",
                "severity": incident.severity,
                "session_id": "system",
                "agent": "incident-detector",
                "timestamp": incident.detected_at,
                "payload": {
                    "incident_id": incident.id,
                    "anomaly_type": incident.anomaly_type.value,
                    "context": incident.context,
                    "suggested_actions": incident.suggested_actions,
                },
            })
        except ImportError:
            logger.debug("[AlertManager] siem_routes not available — SIEM dispatch skipped")

    async def _dispatch_webhook(self, incident: Incident) -> None:
        """POST incident JSON to configured webhook URL."""
        url = os.environ.get("IRONCORE_ALERT_WEBHOOK_URL", "")
        if not url:
            logger.debug("[AlertManager] IRONCORE_ALERT_WEBHOOK_URL not set — webhook skipped")
            return
        try:
            import aiohttp
            payload = {
                "incident_id": incident.id,
                "anomaly_type": incident.anomaly_type.value,
                "severity": incident.severity,
                "detected_at": incident.detected_at,
                "context": incident.context,
                "suggested_actions": incident.suggested_actions,
            }
            async with aiohttp.ClientSession() as session:
                await session.post(
                    url, json=payload,
                    timeout=aiohttp.ClientTimeout(total=5),
                )
            logger.info("[AlertManager] Webhook dispatched to %s", url)
        except ImportError:
            logger.debug("[AlertManager] aiohttp not installed — webhook skipped")

    async def _dispatch_telegram(self, incident: Incident) -> None:
        """Send a Telegram message via Bot API."""
        token = os.environ.get("IRONCORE_TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("IRONCORE_TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            logger.debug("[AlertManager] Telegram not configured — skipped")
            return
        text = (
            f"🚨 *IronCore Alert*\n"
            f"Type: `{incident.anomaly_type.value}`\n"
            f"Severity: *{incident.severity.upper()}*\n"
            f"Context: {incident.context}\n"
            f"Actions: {', '.join(incident.suggested_actions[:2])}"
        )
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                await session.post(
                    url,
                    json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                    timeout=aiohttp.ClientTimeout(total=5),
                )
            logger.info("[AlertManager] Telegram message sent to chat_id=%s", chat_id)
        except ImportError:
            logger.debug("[AlertManager] aiohttp not installed — Telegram skipped")

    async def _dispatch_email(self, incident: Incident) -> None:
        """Send alert via SMTP email."""
        host = os.environ.get("IRONCORE_SMTP_HOST", "")
        if not host:
            logger.debug("[AlertManager] IRONCORE_SMTP_HOST not set — email skipped")
            return
        port = int(os.environ.get("IRONCORE_SMTP_PORT", "587"))
        from_addr = os.environ.get("IRONCORE_SMTP_FROM", "ironcore@internal")
        to_addr = os.environ.get("IRONCORE_SMTP_TO", "")
        if not to_addr:
            logger.debug("[AlertManager] IRONCORE_SMTP_TO not set — email skipped")
            return
        subject = f"[IronCore] {incident.severity.upper()} Alert: {incident.anomaly_type.value}"
        body = (
            f"Incident ID: {incident.id}\n"
            f"Type: {incident.anomaly_type.value}\n"
            f"Severity: {incident.severity}\n"
            f"Detected at: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(incident.detected_at))}\n"
            f"Context: {incident.context}\n"
            f"Suggested actions:\n"
            + "\n".join(f"  - {a}" for a in incident.suggested_actions)
        )
        try:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = from_addr
            msg["To"] = to_addr
            with smtplib.SMTP(host, port) as smtp:
                smtp.starttls()
                smtp.sendmail(from_addr, [to_addr], msg.as_string())
            logger.info("[AlertManager] Email sent to %s", to_addr)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AlertManager] Email dispatch failed: %s", exc)

    # ── Stats ─────────────────────────────────────────────────────────────────

    @property
    def sent_count(self) -> int:
        return self._sent_count

    @property
    def failed_count(self) -> int:
        return self._failed_count
