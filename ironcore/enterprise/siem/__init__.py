"""ironcore/enterprise/siem — Phase 11: SIEM/SOC Integration.

Exports:
    CEFSeverity      — severity enum (UNKNOWN, LOW, MEDIUM, HIGH, CRITICAL)
    CEFFormatter     — converts AuditLogEntry → CEF format string
    BaseSIEMTransport — abstract transport base
    SplunkHECTransport — Splunk HTTP Event Collector
    SyslogTCPTransport — RFC 5424 Syslog over TCP/TLS
    DatadogTransport   — Datadog Log Management API
    SIEMStreamer       — reliable ring-buffer streamer with DLP masking
"""

from ironcore.enterprise.siem.cef_formatter import CEFFormatter, CEFSeverity
from ironcore.enterprise.siem.streamer import SIEMStreamer
from ironcore.enterprise.siem.transports import (
    BaseSIEMTransport,
    DatadogTransport,
    SplunkHECTransport,
    SyslogTCPTransport,
)

__all__ = [
    "CEFSeverity",
    "CEFFormatter",
    "BaseSIEMTransport",
    "SplunkHECTransport",
    "SyslogTCPTransport",
    "DatadogTransport",
    "SIEMStreamer",
]
