"""PII detection patterns for the IronCore DLP Engine.

All patterns are pre-compiled at module-load time for performance.
Target: < 5 ms for text ≤ 10 000 characters.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Dict

from pydantic import BaseModel


# ══════════════════════════════════════════════════════════════════════════════
#  PII types
# ══════════════════════════════════════════════════════════════════════════════

class PIIType(str, Enum):
    CREDIT_CARD    = "credit_card"      # Visa / MC / Amex — Luhn validated
    DEBIT_CARD     = "debit_card"       # Generic 16-digit card
    BANK_ACCOUNT   = "bank_account"     # 9–16 digit VN bank account numbers
    NATIONAL_ID_VN = "national_id_vn"  # CCCD — 12 digits
    PASSPORT_VN    = "passport_vn"     # B + 7 digits
    PHONE_VN       = "phone_vn"        # 0[3-9]xxxxxxxx
    EMAIL          = "email"
    JWT_TOKEN      = "jwt_token"       # eyJ...
    IBAN           = "iban"
    SWIFT_BIC      = "swift_bic"
    IP_ADDRESS     = "ip_address"      # IPv4
    TAX_CODE_VN    = "tax_code_vn"     # MST — 10 or 13 digits
    DATE_OF_BIRTH  = "date_of_birth"   # dd/mm/yyyy or dd-mm-yyyy


# ══════════════════════════════════════════════════════════════════════════════
#  Luhn algorithm
# ══════════════════════════════════════════════════════════════════════════════

def luhn_check(number: str) -> bool:
    """Return True if *number* (digits only) passes the Luhn checksum."""
    digits = [int(c) for c in number if c.isdigit()]
    if len(digits) < 13:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ══════════════════════════════════════════════════════════════════════════════
#  Data model
# ══════════════════════════════════════════════════════════════════════════════

class PIIMatch(BaseModel):
    pii_type: PIIType
    original: str
    masked: str
    token: str
    start: int
    end: int


# ══════════════════════════════════════════════════════════════════════════════
#  Pre-compiled patterns  (order matters — most specific first)
# ══════════════════════════════════════════════════════════════════════════════

COMPILED_PATTERNS: Dict[PIIType, re.Pattern] = {  # type: ignore[type-arg]

    # JWT — eyJ<header>.<payload>.<sig>  (must come before NATIONAL_ID to avoid overlap)
    PIIType.JWT_TOKEN: re.compile(
        r'\beyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\b'
    ),

    # IBAN  (starts with 2 uppercase letters + 2 digits + up to 30 alphanum)
    PIIType.IBAN: re.compile(
        r'\b[A-Z]{2}[0-9]{2}[A-Z0-9]{4,30}\b'
    ),

    # SWIFT / BIC  (8 or 11 chars)
    PIIType.SWIFT_BIC: re.compile(
        r'\b[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b'
    ),

    # Credit card (Visa / MC / Amex / formatted)
    PIIType.CREDIT_CARD: re.compile(
        r'\b(?:'
        r'4[0-9]{12}(?:[0-9]{3})?'           # Visa 13 or 16 digits
        r'|5[1-5][0-9]{14}'                   # Mastercard 16 digits
        r'|3[47][0-9]{13}'                    # Amex 15 digits
        r'|(?:[0-9]{4}[-\s]){3}[0-9]{3,4}'   # Formatted  xxxx-xxxx-xxxx-xxxx
        r')\b'
    ),

    # Vietnamese passport  B followed by 7 digits
    PIIType.PASSPORT_VN: re.compile(r'\bB[0-9]{7}\b'),

    # Vietnamese national ID  (CCCD) — exactly 12 digits
    PIIType.NATIONAL_ID_VN: re.compile(r'\b[0-9]{12}\b'),

    # Vietnamese tax code  (MST) — 10 or 13 digits (13 = with branch suffix)
    PIIType.TAX_CODE_VN: re.compile(r'\b[0-9]{10}(?:-[0-9]{3})?\b'),

    # Vietnamese phone number  0[3-9]xxxxxxxx
    PIIType.PHONE_VN: re.compile(r'\b0[3-9][0-9]{8}\b'),

    # Email
    PIIType.EMAIL: re.compile(
        r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'
    ),

    # IPv4
    PIIType.IP_ADDRESS: re.compile(
        r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}'
        r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'
    ),

    # Date of birth  dd/mm/yyyy or dd-mm-yyyy
    PIIType.DATE_OF_BIRTH: re.compile(
        r'\b(?:0[1-9]|[12][0-9]|3[01])[/\-](?:0[1-9]|1[0-2])[/\-](?:19|20)[0-9]{2}\b'
    ),
}
