"""DLP Engine — core detection, masking, tokenisation and audit logic.

Two modes of operation:

* **Tokenise mode** (default) — replaces PII with reversible placeholder
  tokens so the LLM can still reason about structure while never seeing
  raw sensitive values.
* **Mask mode** — replaces PII with ``*`` characters (used for logs and
  responses sent back to users).

Usage::

    os.environ["IRONCORE_EDITION"] = "enterprise"
    engine = DLPEngine()
    masked = engine.mask("My card is 4111111111111111")
    # → "My card is ************1111"

    tokenised, token_map = engine.tokenize("Send to alice@example.com")
    # → ("Send to [EMAIL_a1b2]", {"[EMAIL_a1b2]": "alice@example.com"})

    original = engine.detokenize(tokenised, token_map)
    # → "Send to alice@example.com"
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import time
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel

from ironcore.edition import check_enterprise
from ironcore.enterprise.dlp.patterns import (
    COMPILED_PATTERNS,
    PIIMatch,
    PIIType,
    luhn_check,
)

logger = logging.getLogger(__name__)

# Alert threshold — if exceeded, DLPThresholdError is raised
_DEFAULT_ALERT_THRESHOLD = 100


# ══════════════════════════════════════════════════════════════════════════════
#  Ancillary models
# ══════════════════════════════════════════════════════════════════════════════

class DLPAlert(BaseModel):
    """Audit event emitted when a PII threshold is exceeded."""

    timestamp: float
    pii_type: str           # PIIType value (str for serialisation)
    source: str             # "llm_prompt" | "log" | "response" | "tool_output"
    session_id: str
    count: int              # Number of matches — NOT the raw values


class DLPThresholdError(Exception):
    """Raised when a single text contains more PII items than the threshold."""

    def __init__(self, count: int, threshold: int) -> None:
        super().__init__(
            f"DLP threshold exceeded: {count} PII items found (limit={threshold}). "
            "Possible bulk-data exposure — request blocked."
        )
        self.count = count
        self.threshold = threshold


# ══════════════════════════════════════════════════════════════════════════════
#  Masking helpers
# ══════════════════════════════════════════════════════════════════════════════

def _mask_value(pii_type: PIIType, value: str, mask_char: str = "*") -> str:
    """Return a context-aware masked representation of *value*."""
    mc = mask_char

    if pii_type in (PIIType.CREDIT_CARD, PIIType.DEBIT_CARD):
        digits = re.sub(r'[\s\-]', '', value)
        # Keep last 4 digits visible
        masked_digits = mc * (len(digits) - 4) + digits[-4:]
        # Reconstruct formatting (groups of 4)
        groups = [masked_digits[i:i + 4] for i in range(0, len(masked_digits), 4)]
        sep = '-' if '-' in value else (' ' if ' ' in value else '')
        return sep.join(groups) if sep else masked_digits

    if pii_type == PIIType.EMAIL:
        local, _, domain = value.partition('@')
        if len(local) <= 2:
            masked_local = mc * len(local)
        else:
            masked_local = local[0] + mc * (len(local) - 1)
        domain_parts = domain.split('.')
        masked_domain = (domain_parts[0][0] + mc * (len(domain_parts[0]) - 1)
                         if domain_parts[0] else mc)
        rest = '.' + '.'.join(domain_parts[1:]) if len(domain_parts) > 1 else ''
        return f"{masked_local}@{masked_domain}{rest}"

    if pii_type == PIIType.PHONE_VN:
        # Keep first 3 and last 2 digits
        return value[:3] + mc * (len(value) - 5) + value[-2:]

    if pii_type == PIIType.NATIONAL_ID_VN:
        return mc * (len(value) - 4) + value[-4:]

    if pii_type == PIIType.PASSPORT_VN:
        return value[0] + mc * (len(value) - 3) + value[-2:]

    if pii_type == PIIType.JWT_TOKEN:
        # Show "eyJ..." prefix and last 4 chars
        return value[:6] + mc * 10 + value[-4:]

    if pii_type == PIIType.IP_ADDRESS:
        parts = value.split('.')
        return '.'.join(parts[:2] + [mc * len(p) for p in parts[2:]])

    # Default: mask middle, show first and last char when > 4 chars
    if len(value) <= 4:
        return mc * len(value)
    return value[0] + mc * (len(value) - 2) + value[-1]


# ══════════════════════════════════════════════════════════════════════════════
#  DLPEngine
# ══════════════════════════════════════════════════════════════════════════════

class DLPEngine:
    """Enterprise DLP engine for PII detection, masking and tokenisation.

    Requires ``IRONCORE_EDITION=enterprise``.
    """

    def __init__(
        self,
        mask_char: str = "*",
        tokenize_mode: bool = True,
        enabled_types: Optional[List[PIIType]] = None,
        alert_threshold: int = _DEFAULT_ALERT_THRESHOLD,
    ) -> None:
        check_enterprise("dlp_engine")
        self._mask_char = mask_char
        self._tokenize_mode = tokenize_mode
        self._enabled: List[PIIType] = enabled_types if enabled_types is not None else list(PIIType)
        self._alert_threshold = alert_threshold

    # ── Public API ────────────────────────────────────────────────────────────

    def scan(self, text: str) -> List[PIIMatch]:
        """Scan *text* and return all PII matches.

        Credit / debit card numbers are Luhn-validated to reduce false positives.
        """
        matches: List[PIIMatch] = []
        for pii_type in self._enabled:
            pattern = COMPILED_PATTERNS.get(pii_type)
            if pattern is None:
                continue
            for m in pattern.finditer(text):
                raw = m.group(0)
                # Luhn gate for card types
                if pii_type in (PIIType.CREDIT_CARD, PIIType.DEBIT_CARD):
                    digits = re.sub(r'[\s\-]', '', raw)
                    if not luhn_check(digits):
                        continue
                masked = _mask_value(pii_type, raw, self._mask_char)
                token = self._make_token(pii_type)
                matches.append(
                    PIIMatch(
                        pii_type=pii_type,
                        original=raw,
                        masked=masked,
                        token=token,
                        start=m.start(),
                        end=m.end(),
                    )
                )
        # Sort by start position so callers can process in order
        matches.sort(key=lambda x: x.start)
        # Deduplicate overlapping spans — keep earliest-encountered match per span
        deduped: List[PIIMatch] = []
        last_end = -1
        for m in matches:
            if m.start >= last_end:
                deduped.append(m)
                last_end = m.end
        return deduped

    def mask(self, text: str) -> str:
        """Replace all detected PII with masked equivalents."""
        matches = self.scan(text)
        if not matches:
            return text
        # Process in reverse order to preserve offsets
        result = text
        for m in reversed(matches):
            result = result[: m.start] + m.masked + result[m.end :]
        return result

    def tokenize(self, text: str) -> Tuple[str, Dict[str, str]]:
        """Replace all detected PII with reversible token placeholders.

        Returns ``(tokenised_text, token_map)`` where ``token_map`` maps
        each placeholder token back to the original value.
        """
        matches = self.scan(text)
        token_map: Dict[str, str] = {}
        result = text
        for m in reversed(matches):
            token_map[m.token] = m.original
            result = result[: m.start] + m.token + result[m.end :]
        return result, token_map

    def detokenize(self, text: str, token_map: Dict[str, str]) -> str:
        """Reverse a previous tokenisation using *token_map*."""
        result = text
        for token, original in token_map.items():
            result = result.replace(token, original)
        return result

    def audit_scan(
        self,
        text: str,
        source: str = "",
        session_id: str = "",
    ) -> Optional[DLPAlert]:
        """Scan *text* and emit an audit log entry for any PII found.

        The raw PII values are **never** written to the log — only the
        type and character positions are recorded.

        Raises :exc:`DLPThresholdError` if the number of PII items exceeds
        :attr:`_alert_threshold`.

        Returns a :class:`DLPAlert` if PII was found, else *None*.
        """
        matches = self.scan(text)
        if not matches:
            return None

        count = len(matches)
        # Log only type + position — no raw values
        for m in matches:
            logger.warning(
                "[DLP] PII detected | type=%s source=%s session=%s pos=%d-%d",
                m.pii_type,
                source or "unknown",
                session_id or "unknown",
                m.start,
                m.end,
            )

        alert = DLPAlert(
            timestamp=time.time(),
            pii_type=str(matches[0].pii_type),
            source=source,
            session_id=session_id,
            count=count,
        )

        if count > self._alert_threshold:
            raise DLPThresholdError(count=count, threshold=self._alert_threshold)

        return alert

    # ── Class-method constructors ─────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "DLPEngine":
        """Build a DLPEngine from environment variables."""
        types_raw = os.getenv("IRONCORE_DLP_TYPES", "")
        enabled: Optional[List[PIIType]] = None
        if types_raw:
            enabled = []
            for t in types_raw.split(","):
                t = t.strip()
                try:
                    enabled.append(PIIType(t))
                except ValueError:
                    logger.warning("[DLP] Unknown PII type in IRONCORE_DLP_TYPES: %s", t)
        return cls(
            mask_char=os.getenv("IRONCORE_DLP_MASK_CHAR", "*"),
            tokenize_mode=os.getenv("IRONCORE_DLP_TOKENIZE", "true").lower() == "true",
            enabled_types=enabled,
            alert_threshold=int(os.getenv("IRONCORE_DLP_ALERT_THRESHOLD", "100")),
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _make_token(pii_type: PIIType) -> str:
        tag = pii_type.value.upper().replace("_", "")[:8]
        return f"[{tag}_{secrets.token_hex(2)}]"
