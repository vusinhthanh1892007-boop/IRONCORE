"""MakerCheckerEngine — 4-Eyes Principle approval orchestrator.

Redis is used for persistent ticket storage so approvals survive restarts.
In-memory fallback is provided for tests and development (pass ``redis_client=None``).

Digital signatures use HMAC-SHA256 so the approver's session key never leaves
their session, and the signature can be independently verified by auditors.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional

from ironcore.edition import check_enterprise
from ironcore.enterprise.hitl.models import (
    ApprovalRejectedError,
    ApprovalStatus,
    ApprovalTicket,
    ApprovalTimeoutError,
)
from ironcore.enterprise.hitl.notifiers import (
    JiraConfig,
    JiraNotifier,
    SlackConfig,
    SlackNotifier,
    TeamsConfig,
    TeamsNotifier,
)

logger = logging.getLogger(__name__)

# Redis TTL: 25 hours (ticket expires at 24h but keep extra hour for audit queries)
_REDIS_TTL_SECONDS = 25 * 3600
_REDIS_KEY_PREFIX = "ironcore:hitl:ticket:"


def _ticket_key(ticket_id: str) -> str:
    return f"{_REDIS_KEY_PREFIX}{ticket_id}"


def _make_signature(ticket_id: str, approver_id: str, timestamp: float, session_key: str) -> str:
    """Return HMAC-SHA256 hex digest of ticket_id + approver_id + timestamp."""
    message = f"{ticket_id}:{approver_id}:{timestamp:.6f}".encode()
    return hmac.new(session_key.encode(), message, hashlib.sha256).hexdigest()


class MakerCheckerEngine:
    """Enterprise 4-Eyes approval engine.

    Requires ``IRONCORE_EDITION=enterprise``.
    """

    def __init__(
        self,
        redis_client: Any = None,
        jira_config: Optional[JiraConfig] = None,
        slack_config: Optional[SlackConfig] = None,
        teams_config: Optional[TeamsConfig] = None,
        approval_timeout_hours: int = 24,
        http_client: Any = None,   # injected for notifiers (tests pass a mock)
    ) -> None:
        check_enterprise("maker_checker")
        self._redis = redis_client
        self._approval_timeout_hours = approval_timeout_hours
        # In-memory store used when Redis is not provided (development/tests)
        self._memory_store: Dict[str, str] = {}

        # Notifiers (only configured if respective config present)
        self._jira: Optional[JiraNotifier] = (
            JiraNotifier(jira_config, http_client=http_client) if jira_config else None
        )
        self._slack: Optional[SlackNotifier] = (
            SlackNotifier(slack_config, http_client=http_client) if slack_config else None
        )
        self._teams: Optional[TeamsNotifier] = (
            TeamsNotifier(teams_config, http_client=http_client) if teams_config else None
        )

    # ── Storage helpers ───────────────────────────────────────────────────────

    async def _save(self, ticket: ApprovalTicket) -> None:
        data = ticket.model_dump_json()
        key = _ticket_key(ticket.ticket_id)
        if self._redis is not None:
            await self._redis.setex(key, _REDIS_TTL_SECONDS, data)
        else:
            self._memory_store[key] = data

    async def _load(self, ticket_id: str) -> Optional[ApprovalTicket]:
        key = _ticket_key(ticket_id)
        if self._redis is not None:
            raw = await self._redis.get(key)
        else:
            raw = self._memory_store.get(key)
        if raw is None:
            return None
        return ApprovalTicket.model_validate_json(raw)

    # ── Public API ────────────────────────────────────────────────────────────

    async def request_approval(
        self,
        session_id: str,
        action_type: str,
        action_payload: Dict[str, Any],
        risk_reason: str,
        approver_ids: List[str],
        required_approvals: int = 1,
        requestor_id: str = "ai-agent",
    ) -> ApprovalTicket:
        """Create an approval ticket and notify all configured channels.

        Returns the ticket with ``status=PENDING``.  The caller should then
        call :meth:`wait_for_approval` to block until a decision is made.
        """
        timeout_seconds = self._approval_timeout_hours * 3600
        ticket = ApprovalTicket(
            session_id=session_id,
            action_type=action_type,
            action_payload=action_payload,
            risk_level="CRITICAL",
            risk_reason=risk_reason,
            requestor_id=requestor_id,
            approver_ids=approver_ids,
            required_approvals=required_approvals,
            expires_at=time.time() + timeout_seconds,
        )

        await self._save(ticket)
        logger.info(
            "[HITL] Approval ticket created | id=%s action=%s session=%s",
            ticket.ticket_id, action_type, session_id,
        )

        # Fan-out notifications (errors are logged, not raised — ticket already persisted)
        if self._jira:
            try:
                key = await self._jira.create_issue(ticket)
                ticket.jira_issue_key = key
                await self._save(ticket)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[HITL] Jira notification failed: %s", exc)

        if self._slack:
            try:
                ts = await self._slack.send_approval_request(ticket)
                ticket.slack_message_ts = ts
                await self._save(ticket)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[HITL] Slack notification failed: %s", exc)

        if self._teams:
            try:
                await self._teams.send_approval_request(ticket)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[HITL] Teams notification failed: %s", exc)

        return ticket

    async def wait_for_approval(
        self,
        ticket_id: str,
        poll_interval: float = 5.0,
    ) -> ApprovalTicket:
        """Poll until the ticket reaches a terminal state.

        Raises :exc:`ApprovalTimeoutError` if the ticket expires.
        """
        while True:
            ticket = await self._load(ticket_id)
            if ticket is None:
                raise ApprovalTimeoutError(ticket_id)

            # Lazily mark expired
            if ticket.status == ApprovalStatus.PENDING and ticket.is_expired:
                ticket.status = ApprovalStatus.EXPIRED
                await self._save(ticket)
                logger.warning("[HITL] Ticket %s has expired.", ticket_id)
                raise ApprovalTimeoutError(ticket_id)

            if ticket.is_terminal:
                return ticket

            await asyncio.sleep(poll_interval)

    async def approve(
        self,
        ticket_id: str,
        approver_id: str,
        approver_session_key: str,
        notes: str = "",
    ) -> ApprovalTicket:
        """Approve a pending ticket.

        Creates an HMAC digital signature and moves status to APPROVED.
        Raises ``ValueError`` if the approver is not in the allowlist or the
        ticket is already in a terminal state.
        """
        ticket = await self._load(ticket_id)
        if ticket is None:
            raise ValueError(f"Ticket {ticket_id!r} not found.")
        if ticket.is_expired:
            ticket.status = ApprovalStatus.EXPIRED
            await self._save(ticket)
            raise ApprovalTimeoutError(ticket_id)
        if ticket.is_terminal:
            raise ValueError(
                f"Ticket {ticket_id!r} is already in terminal state {ticket.status!r}."
            )
        if approver_id not in ticket.approver_ids:
            raise ValueError(
                f"{approver_id!r} is not in the approver allowlist for ticket {ticket_id!r}."
            )

        approved_at = time.time()
        signature = _make_signature(ticket_id, approver_id, approved_at, approver_session_key)

        ticket.status = ApprovalStatus.APPROVED
        ticket.approved_by = approver_id
        ticket.approved_at = approved_at
        ticket.digital_signature = signature

        await self._save(ticket)
        logger.info(
            "[HITL] Ticket %s APPROVED by %s (notes=%r sig=%s...)",
            ticket_id, approver_id, notes, signature[:8],
        )
        return ticket

    async def reject(
        self,
        ticket_id: str,
        approver_id: str,
        reason: str,
    ) -> ApprovalTicket:
        """Reject a pending ticket.

        Raises ``ValueError`` for unknown approvers or terminal tickets.
        """
        ticket = await self._load(ticket_id)
        if ticket is None:
            raise ValueError(f"Ticket {ticket_id!r} not found.")
        if ticket.is_terminal:
            raise ValueError(
                f"Ticket {ticket_id!r} is already in terminal state {ticket.status!r}."
            )
        if approver_id not in ticket.approver_ids:
            raise ValueError(
                f"{approver_id!r} is not in the approver allowlist for ticket {ticket_id!r}."
            )

        ticket.status = ApprovalStatus.REJECTED
        ticket.approved_by = approver_id
        ticket.rejection_reason = reason
        ticket.approved_at = time.time()

        await self._save(ticket)
        logger.info(
            "[HITL] Ticket %s REJECTED by %s reason=%r",
            ticket_id, approver_id, reason,
        )
        return ticket

    async def revoke(
        self,
        ticket_id: str,
        revoker_id: str,
        reason: str,
    ) -> ApprovalTicket:
        """Revoke a previously approved ticket."""
        ticket = await self._load(ticket_id)
        if ticket is None:
            raise ValueError(f"Ticket {ticket_id!r} not found.")
        if ticket.status != ApprovalStatus.APPROVED:
            raise ValueError(
                f"Only APPROVED tickets can be revoked. Current status: {ticket.status!r}"
            )
        ticket.status = ApprovalStatus.REVOKED
        ticket.rejection_reason = f"Revoked by {revoker_id}: {reason}"
        await self._save(ticket)
        logger.warning("[HITL] Ticket %s REVOKED by %s: %s", ticket_id, revoker_id, reason)
        return ticket

    async def get_ticket(self, ticket_id: str) -> Optional[ApprovalTicket]:
        """Retrieve a ticket by ID.  Returns ``None`` if not found."""
        return await self._load(ticket_id)

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, redis_client: Any = None, http_client: Any = None) -> "MakerCheckerEngine":
        """Build a MakerCheckerEngine from environment variables."""
        import os

        jira_url = os.getenv("IRONCORE_JIRA_URL", "")
        jira_token = os.getenv("IRONCORE_JIRA_TOKEN", "")
        jira_project = os.getenv("IRONCORE_JIRA_PROJECT", "IRON")
        jira_cfg = JiraConfig(
            base_url=jira_url, token=jira_token, project_key=jira_project
        ) if jira_url and jira_token else None

        slack_token = os.getenv("IRONCORE_SLACK_BOT_TOKEN", "")
        slack_channel = os.getenv("IRONCORE_SLACK_APPROVAL_CHANNEL", "#ai-approvals")
        slack_cfg = SlackConfig(
            bot_token=slack_token, channel=slack_channel
        ) if slack_token else None

        teams_webhook = os.getenv("IRONCORE_TEAMS_WEBHOOK_URL", "")
        teams_cfg = TeamsConfig(webhook_url=teams_webhook) if teams_webhook else None

        timeout_hours = int(os.getenv("IRONCORE_APPROVAL_TIMEOUT_HOURS", "24"))

        return cls(
            redis_client=redis_client,
            jira_config=jira_cfg,
            slack_config=slack_cfg,
            teams_config=teams_cfg,
            approval_timeout_hours=timeout_hours,
            http_client=http_client,
        )
