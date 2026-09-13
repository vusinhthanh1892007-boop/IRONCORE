"""CEF (Common Event Format) formatter for IronCore audit events.

Converts ``AuditLogEntry`` objects into CEF-formatted strings suitable for
ingestion by Splunk, IBM QRadar, HP ArcSight, and any RFC 5424-compatible SIEM.

CEF format (one line per event)::

    CEF:0|Vendor|Product|Version|SignatureID|Name|Severity|Extension

Extension is Key=Value pairs separated by spaces.  Special characters in
header fields (``|`` and ``\\``) and in extension values (``=``, ``\\``,
newlines) must be escaped as per the CEF specification.

Requires ``IRONCORE_EDITION=enterprise``.
"""

from __future__ import annotations

import json
import logging
import time
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple

from ironcore.edition import check_enterprise
from ironcore.monitoring.schemas import AuditLogEntry

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Severity enum
# ══════════════════════════════════════════════════════════════════════════════

class CEFSeverity(IntEnum):
    UNKNOWN  = 0
    LOW      = 3
    MEDIUM   = 5
    HIGH     = 7
    CRITICAL = 10


# ══════════════════════════════════════════════════════════════════════════════
#  Event → (sig_id, name, severity) mapping
# ══════════════════════════════════════════════════════════════════════════════

_EVENT_MAP: Dict[str, Tuple[str, str, CEFSeverity]] = {
    "action_executed":    ("100", "AI Action Executed",              CEFSeverity.LOW),
    "critical_action":    ("200", "Critical AI Action",              CEFSeverity.HIGH),
    "policy_violation":   ("300", "Policy Violation Detected",       CEFSeverity.HIGH),
    "approval_requested": ("400", "Maker-Checker Approval Requested",CEFSeverity.MEDIUM),
    "approval_granted":   ("401", "Action Approved",                 CEFSeverity.MEDIUM),
    "approval_rejected":  ("402", "Action Rejected",                 CEFSeverity.MEDIUM),
    "dlp_pii_detected":   ("500", "PII Detected in AI Flow",         CEFSeverity.HIGH),
    "auth_success":       ("600", "Authentication Success",          CEFSeverity.LOW),
    "auth_failure":       ("601", "Authentication Failure",          CEFSeverity.HIGH),
    "airgap_violation":   ("700", "Network Egress Violation",        CEFSeverity.CRITICAL),
}

_UNKNOWN_EVENT: Tuple[str, str, CEFSeverity] = (
    "999", "Unknown IronCore Event", CEFSeverity.UNKNOWN
)


# ══════════════════════════════════════════════════════════════════════════════
#  CEF escaping helpers
# ══════════════════════════════════════════════════════════════════════════════

def _escape_header(value: str) -> str:
    """Escape CEF header field: backslash and pipe must be escaped."""
    return value.replace("\\", "\\\\").replace("|", "\\|")


def _escape_extension(value: str) -> str:
    """Escape CEF extension value: backslash, equals-sign, newlines."""
    return (
        value.replace("\\", "\\\\")
             .replace("=", "\\=")
             .replace("\n", "\\n")
             .replace("\r", "\\r")
    )


def _payload_summary(payload: Dict[str, Any], max_chars: int = 200) -> str:
    """Produce a compact, single-line summary of the event payload."""
    try:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raw = str(payload)
    if len(raw) > max_chars:
        raw = raw[:max_chars] + "..."
    # Remove newlines that would break the single-line CEF format
    return raw.replace("\n", " ").replace("\r", " ")


# ══════════════════════════════════════════════════════════════════════════════
#  CEFFormatter
# ══════════════════════════════════════════════════════════════════════════════

class CEFFormatter:
    """Convert ``AuditLogEntry`` objects to CEF-format strings.

    Requires ``IRONCORE_EDITION=enterprise``.

    Usage::

        formatter = CEFFormatter()
        line = formatter.format(entry)
        # "CEF:0|IronCore|IronCore-AI-Platform|2.0|100|AI Action Executed|3|..."
    """

    VENDOR  = "IronCore"
    PRODUCT = "IronCore-AI-Platform"
    VERSION = "2.0"

    def __init__(self, hostname: str = "ironcore") -> None:
        check_enterprise("siem_integration")
        self._hostname = hostname

    # ── Public API ────────────────────────────────────────────────────────────

    def format(self, entry: AuditLogEntry) -> str:
        """Convert a single AuditLogEntry to a CEF line (no trailing newline)."""
        sig_id, name, severity = _EVENT_MAP.get(entry.event_type, _UNKNOWN_EVENT)

        # --- Header (pipe-separated, 8 fields) --------------------------------
        header = "|".join([
            "CEF:0",
            _escape_header(self.VENDOR),
            _escape_header(self.PRODUCT),
            _escape_header(self.VERSION),
            _escape_header(sig_id),
            _escape_header(name),
            str(int(severity)),
        ])

        # --- Extension (Key=Value pairs) --------------------------------------
        # rt  = receipt time in epoch milliseconds
        # suser = source user / session id
        # dvchost = originating host
        # act   = action / event type
        # cs1   = sequence number (custom string 1)
        # msg   = payload summary
        rt_ms = int(entry.timestamp * 1000)
        ext_pairs = [
            f"rt={rt_ms}",
            f"suser={_escape_extension(entry.session_id)}",
            f"dvchost={_escape_extension(self._hostname)}",
            f"act={_escape_extension(entry.event_type)}",
            f"cs1={_escape_extension(entry.agent)}",
            f"cs1Label=agent",
            f"cs2={_escape_extension(str(entry.seq))}",
            f"cs2Label=seq",
            f"msg={_escape_extension(_payload_summary(entry.payload))}",
        ]
        extension = " ".join(ext_pairs)

        return f"{header}|{extension}"

    def format_batch(self, entries: List[AuditLogEntry]) -> List[str]:
        """Format a list of entries; silently skip any that raise."""
        results: List[str] = []
        for entry in entries:
            try:
                results.append(self.format(entry))
            except Exception as exc:
                logger.warning("[CEFFormatter] Skipped entry seq=%s: %s", getattr(entry, "seq", "?"), exc)
        return results

    @classmethod
    def from_env(cls) -> "CEFFormatter":
        """Construct from environment (IRONCORE_SIEM_HOSTNAME)."""
        import os
        hostname = os.getenv("IRONCORE_SIEM_HOSTNAME", "ironcore")
        return cls(hostname=hostname)
