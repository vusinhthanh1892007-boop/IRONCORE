"""HITL approval models.

All models are serialisable via Pydantic so they can be stored in Redis as JSON.
"""

from __future__ import annotations

import secrets
import time
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ApprovalStatus(str, Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED  = "expired"
    REVOKED  = "revoked"   # Approved then retroactively revoked


class ApprovalTicket(BaseModel):
    ticket_id: str = Field(
        default_factory=lambda: f"IRON-{secrets.token_hex(6).upper()}"
    )
    session_id: str
    action_type: str              # e.g. "update_credit_limit", "transfer_funds"
    action_payload: Dict[str, Any]  # PII must be masked before storing
    risk_level: str               # "CRITICAL"
    risk_reason: str              # Why this action is critical
    requestor_id: str             # User/Agent that proposed the action
    approver_ids: List[str]       # Allowlist of principals who may approve
    required_approvals: int = 1   # 1 = single approval, 2 = dual control
    status: ApprovalStatus = ApprovalStatus.PENDING

    created_at: float = Field(default_factory=time.time)
    expires_at: float = Field(default_factory=lambda: time.time() + 86_400)

    approved_by: Optional[str] = None
    approved_at: Optional[float] = None
    digital_signature: Optional[str] = None

    jira_issue_key: Optional[str] = None
    slack_message_ts: Optional[str] = None

    rejection_reason: Optional[str] = None

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.EXPIRED,
            ApprovalStatus.REVOKED,
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Exceptions
# ══════════════════════════════════════════════════════════════════════════════

class ApprovalTimeoutError(Exception):
    """Raised when an approval ticket expires before a decision is reached."""

    def __init__(self, ticket_id: str) -> None:
        super().__init__(
            f"Approval ticket {ticket_id} expired without a decision. "
            "Action automatically rejected — no change was applied."
        )
        self.ticket_id = ticket_id


class ApprovalRejectedError(Exception):
    """Raised when a ticket is explicitly rejected by an approver."""

    def __init__(self, ticket_id: str, approver_id: str, reason: str) -> None:
        super().__init__(
            f"Action rejected by {approver_id}: {reason} (ticket={ticket_id})"
        )
        self.ticket_id = ticket_id
        self.approver_id = approver_id
        self.reason = reason
