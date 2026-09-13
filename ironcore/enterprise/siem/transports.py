"""SIEM transport implementations for IronCore Phase 11.

Transports are responsible for delivering batches of CEF-format strings to
external SIEM systems.  Each transport follows the same interface:

    await transport.send(cef_lines)   — deliver a list of CEF strings
    await transport.health_check()    — return True if backend reachable

All transports accept an optional ``http_client`` (or use a socket stub) so
that tests can mock the network layer without requiring real SIEM services.

Supported backends:
- ``SplunkHECTransport``  — Splunk HTTP Event Collector (port 8088)
- ``SyslogTCPTransport``  — RFC 5424 Syslog over TCP/TLS (port 514/6514)
- ``DatadogTransport``    — Datadog Log Management API v2
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import time
from abc import ABC, abstractmethod
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Abstract base
# ══════════════════════════════════════════════════════════════════════════════

class BaseSIEMTransport(ABC):
    """Abstract SIEM transport interface."""

    @abstractmethod
    async def send(self, events: List[str]) -> None:
        """Send a batch of CEF-formatted event strings to the SIEM backend."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the SIEM backend is reachable."""


# ══════════════════════════════════════════════════════════════════════════════
#  Splunk HEC Transport
# ══════════════════════════════════════════════════════════════════════════════

class SplunkHECTransport(BaseSIEMTransport):
    """Send events to Splunk via the HTTP Event Collector (HEC).

    Batches up to ``batch_size`` CEF strings into a single POST request.
    Each event is wrapped in the HEC JSON envelope::

        {"event": "<cef-line>", "sourcetype": "cef", "index": "<index>"}

    ``http_client=None`` → stub mode (log and return, no real HTTP).
    """

    def __init__(
        self,
        url: str,
        hec_token: str,
        index: str = "ironcore",
        verify_ssl: bool = True,
        batch_size: int = 100,
        http_client: Any = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._hec_token = hec_token
        self._index = index
        self._verify_ssl = verify_ssl
        self._batch_size = batch_size
        self._http = http_client
        self._endpoint = f"{self._url}/services/collector/event"
        self._health_endpoint = f"{self._url}/services/collector/health"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Splunk {self._hec_token}",
            "Content-Type": "application/json",
        }

    def _build_body(self, events: List[str]) -> str:
        """Build newline-delimited JSON payload (HEC raw batch format)."""
        lines = []
        for cef in events:
            lines.append(json.dumps({
                "event": cef,
                "sourcetype": "cef",
                "index": self._index,
                "time": time.time(),
            }))
        return "\n".join(lines)

    async def send(self, events: List[str]) -> None:
        if not events:
            return
        if self._http is None:
            logger.debug("[SplunkHEC] Stub — would send %d events to %s", len(events), self._endpoint)
            return
        # Chunk into batches
        for i in range(0, len(events), self._batch_size):
            batch = events[i : i + self._batch_size]
            body = self._build_body(batch)
            resp = await self._http.post(self._endpoint, content=body, headers=self._headers())
            resp_json = resp.json() if callable(resp.json) else resp.json
            if isinstance(resp_json, dict) and resp_json.get("code", 0) != 0:
                raise RuntimeError(
                    f"[SplunkHEC] Rejected batch: code={resp_json.get('code')} "
                    f"text={resp_json.get('text', '')}"
                )
            logger.debug("[SplunkHEC] Sent %d events — OK", len(batch))

    async def health_check(self) -> bool:
        if self._http is None:
            return True  # stub is always "healthy"
        try:
            resp = await self._http.get(self._health_endpoint, headers=self._headers())
            resp_json = resp.json() if callable(resp.json) else resp.json
            # HEC health returns {"text":"HEC is healthy","code":17} when healthy
            return isinstance(resp_json, dict) and resp_json.get("code") in (17, 0)
        except Exception as exc:
            logger.warning("[SplunkHEC] Health check failed: %s", exc)
            return False

    @classmethod
    def from_env(cls, http_client: Any = None) -> "SplunkHECTransport":
        return cls(
            url=os.getenv("IRONCORE_SPLUNK_HEC_URL", "https://splunk.bank.internal:8088"),
            hec_token=os.getenv("IRONCORE_SPLUNK_HEC_TOKEN", ""),
            index=os.getenv("IRONCORE_SPLUNK_INDEX", "ironcore"),
            verify_ssl=os.getenv("IRONCORE_SPLUNK_VERIFY_SSL", "true").lower() != "false",
            http_client=http_client,
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Syslog TCP Transport (RFC 5424)
# ══════════════════════════════════════════════════════════════════════════════

class SyslogTCPTransport(BaseSIEMTransport):
    """Send events as RFC 5424 syslog messages over TCP (optionally TLS).

    Compatible with IBM QRadar, HP ArcSight, Microsoft Sentinel.

    ``_socket_factory`` is injectable for testing — set to ``None`` for real
    async TCP connections.
    """

    # Syslog facility: 1 = user-level messages; severity: 5 = notice
    _PRIORITY = 13  # (1 << 3) | 5

    def __init__(
        self,
        host: str,
        port: int = 6514,
        use_tls: bool = True,
        socket_factory: Any = None,  # injected for tests
    ) -> None:
        self._host = host
        self._port = port
        self._use_tls = use_tls
        self._socket_factory = socket_factory  # None → stub mode

    def _wrap_syslog(self, cef_line: str) -> bytes:
        """Wrap a CEF string in a minimal RFC 5424 syslog envelope."""
        import datetime
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        pri = f"<{self._PRIORITY}>"
        # RFC 5424: HEADER = PRI VERSION SP TIMESTAMP SP HOSTNAME SP APPNAME SP PROCID SP MSGID
        header = f"{pri}1 {ts} ironcore IronCore-AI - - -"
        message = f"{header} {cef_line}\n"
        return message.encode("utf-8")

    async def send(self, events: List[str]) -> None:
        if not events:
            return
        if self._socket_factory is None:
            logger.debug("[SyslogTCP] Stub — would send %d events to %s:%d", len(events), self._host, self._port)
            return
        # Real TCP send via injected socket factory
        writer = None
        try:
            reader, writer = await self._socket_factory(self._host, self._port)
            for cef in events:
                writer.write(self._wrap_syslog(cef))
            await writer.drain()
        except Exception as exc:
            logger.error("[SyslogTCP] Send failed: %s", exc)
            raise
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    async def health_check(self) -> bool:
        if self._socket_factory is None:
            return True  # stub
        try:
            reader, writer = await self._socket_factory(self._host, self._port)
            writer.close()
            return True
        except Exception as exc:
            logger.warning("[SyslogTCP] Health check failed: %s", exc)
            return False

    @classmethod
    def from_env(cls, socket_factory: Any = None) -> "SyslogTCPTransport":
        return cls(
            host=os.getenv("IRONCORE_SYSLOG_HOST", "syslog.bank.internal"),
            port=int(os.getenv("IRONCORE_SYSLOG_PORT", "6514")),
            use_tls=os.getenv("IRONCORE_SYSLOG_TLS", "true").lower() != "false",
            socket_factory=socket_factory,
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Datadog Transport
# ══════════════════════════════════════════════════════════════════════════════

class DatadogTransport(BaseSIEMTransport):
    """Send events to Datadog Log Management via API v2.

    Endpoint: ``POST https://http-intake.logs.{site}/api/v2/logs``

    ``http_client=None`` → stub mode.
    """

    def __init__(
        self,
        api_key: str,
        site: str = "datadoghq.com",
        service: str = "ironcore-ai",
        http_client: Any = None,
    ) -> None:
        self._api_key = api_key
        self._site = site
        self._service = service
        self._http = http_client
        self._endpoint = f"https://http-intake.logs.{site}/api/v2/logs"

    def _headers(self) -> dict:
        return {
            "DD-API-KEY": self._api_key,
            "Content-Type": "application/json",
        }

    def _build_payload(self, events: List[str]) -> str:
        logs = [
            {
                "ddsource": "ironcore",
                "ddtags": "env:production,service:ironcore-ai",
                "hostname": "ironcore",
                "service": self._service,
                "message": cef,
            }
            for cef in events
        ]
        return json.dumps(logs)

    async def send(self, events: List[str]) -> None:
        if not events:
            return
        if self._http is None:
            logger.debug("[Datadog] Stub — would send %d events to %s", len(events), self._endpoint)
            return
        body = self._build_payload(events)
        resp = await self._http.post(self._endpoint, content=body, headers=self._headers())
        status = getattr(resp, "status_code", None)
        if status is not None and status not in (200, 202):
            raise RuntimeError(f"[Datadog] HTTP {status} sending {len(events)} events")
        logger.debug("[Datadog] Sent %d events — OK", len(events))

    async def health_check(self) -> bool:
        if self._http is None:
            return True  # stub
        try:
            validate_url = f"https://api.{self._site}/api/v1/validate"
            resp = await self._http.get(validate_url, headers=self._headers())
            resp_json = resp.json() if callable(resp.json) else resp.json
            return isinstance(resp_json, dict) and resp_json.get("valid", False)
        except Exception as exc:
            logger.warning("[Datadog] Health check failed: %s", exc)
            return False

    @classmethod
    def from_env(cls, http_client: Any = None) -> "DatadogTransport":
        return cls(
            api_key=os.getenv("IRONCORE_DATADOG_API_KEY", ""),
            site=os.getenv("IRONCORE_DATADOG_SITE", "datadoghq.com"),
            service=os.getenv("IRONCORE_DATADOG_SERVICE", "ironcore-ai"),
            http_client=http_client,
        )
