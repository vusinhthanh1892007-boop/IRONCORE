"""Notification adapters — Jira, Slack, Microsoft Teams.

All adapters are dependency-free mock-safe: they accept an optional
``http_client`` injection point so tests can stub the HTTP layer without
actually calling external APIs.

Production usage relies on ``httpx.AsyncClient``; this dependency is optional
and only imported at call time so the module loads even without httpx installed.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Config data classes ───────────────────────────────────────────────────────

from dataclasses import dataclass, field


@dataclass
class JiraConfig:
    base_url: str                         # e.g. "https://bank.atlassian.net"
    token: str                            # Bearer token
    project_key: str = "IRON"
    issue_type: str = "Task"


@dataclass
class SlackConfig:
    bot_token: str                        # xoxb-...
    channel: str = "#ai-approvals"       # default channel name/id


@dataclass
class TeamsConfig:
    webhook_url: str                      # incoming webhook URL


# ══════════════════════════════════════════════════════════════════════════════
#  JiraNotifier
# ══════════════════════════════════════════════════════════════════════════════

class JiraNotifier:
    """Creates a Jira issue for every approval ticket.

    The HTTP call is delegated to *http_client* (any object with a
    ``post(url, *, headers, json) -> response`` async method).  When
    *http_client* is ``None`` the notifier logs a warning and returns a
    synthetic issue key so the caller is never blocked.
    """

    def __init__(self, config: JiraConfig, http_client: Any = None) -> None:
        self._cfg = config
        self._http = http_client

    async def create_issue(self, ticket: Any) -> str:
        """Create a Jira issue and return the issue key (e.g. ``IRON-4821``)."""
        payload = {
            "fields": {
                "project": {"key": self._cfg.project_key},
                "summary": f"[IronCore Approval] {ticket.action_type}",
                "description": (
                    f"Ticket ID: {ticket.ticket_id}\n"
                    f"Risk Level: {ticket.risk_level}\n"
                    f"Risk Reason: {ticket.risk_reason}\n"
                    f"Requestor: {ticket.requestor_id}\n"
                    f"Approvers: {', '.join(ticket.approver_ids)}\n"
                    f"Payload (masked): {ticket.action_payload}\n"
                    f"Expires at: {ticket.expires_at}"
                ),
                "issuetype": {"name": self._cfg.issue_type},
                "priority": {"name": "Critical"},
            }
        }
        if self._http is None:
            logger.warning(
                "[Jira] No HTTP client configured — skipping Jira issue creation "
                "for ticket %s", ticket.ticket_id
            )
            return f"{self._cfg.project_key}-MOCK"

        url = f"{self._cfg.base_url}/rest/api/3/issue"
        headers = {
            "Authorization": f"Bearer {self._cfg.token}",
            "Content-Type": "application/json",
        }
        resp = await self._http.post(url, headers=headers, json=payload)
        data = resp.json() if hasattr(resp, "json") else {}
        key = data.get("key", f"{self._cfg.project_key}-ERR")
        logger.info("[Jira] Created issue %s for ticket %s", key, ticket.ticket_id)
        return key


# ══════════════════════════════════════════════════════════════════════════════
#  SlackNotifier
# ══════════════════════════════════════════════════════════════════════════════

class SlackNotifier:
    """Sends a Slack Block Kit message requesting approval."""

    def __init__(self, config: SlackConfig, http_client: Any = None) -> None:
        self._cfg = config
        self._http = http_client

    async def send_approval_request(self, ticket: Any) -> str:
        """Post the approval request to Slack and return the message timestamp."""
        import time as _time

        mention = " ".join(f"<@{uid}>" for uid in ticket.approver_ids)
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"⚠️ AI Action Requires Approval — {ticket.action_type}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Ticket ID*\n{ticket.ticket_id}"},
                    {"type": "mrkdwn", "text": f"*Risk Level*\n{ticket.risk_level}"},
                    {"type": "mrkdwn", "text": f"*Risk Reason*\n{ticket.risk_reason}"},
                    {"type": "mrkdwn", "text": f"*Requestor*\n{ticket.requestor_id}"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Approvers required:* {mention}",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve"},
                        "style": "primary",
                        "value": ticket.ticket_id,
                        "action_id": "approve_ticket",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Reject"},
                        "style": "danger",
                        "value": ticket.ticket_id,
                        "action_id": "reject_ticket",
                    },
                ],
            },
        ]
        payload = {
            "channel": self._cfg.channel,
            "blocks": blocks,
            "text": f"Approval required for {ticket.action_type} ({ticket.ticket_id})",
        }

        if self._http is None:
            logger.warning(
                "[Slack] No HTTP client configured — skipping Slack notification "
                "for ticket %s", ticket.ticket_id
            )
            return f"mock-ts-{int(_time.time())}"

        url = "https://slack.com/api/chat.postMessage"
        headers = {
            "Authorization": f"Bearer {self._cfg.bot_token}",
            "Content-Type": "application/json",
        }
        resp = await self._http.post(url, headers=headers, json=payload)
        data = resp.json() if hasattr(resp, "json") else {}
        ts = data.get("ts", "")
        logger.info("[Slack] Sent approval request ts=%s for ticket %s", ts, ticket.ticket_id)
        return ts


# ══════════════════════════════════════════════════════════════════════════════
#  TeamsNotifier
# ══════════════════════════════════════════════════════════════════════════════

class TeamsNotifier:
    """Sends a Microsoft Teams Adaptive Card via an incoming webhook."""

    def __init__(self, config: TeamsConfig, http_client: Any = None) -> None:
        self._cfg = config
        self._http = http_client

    async def send_approval_request(self, ticket: Any) -> None:
        """Post the approval request card to Teams."""
        card = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "size": "Large",
                                "weight": "Bolder",
                                "text": f"⚠️ AI Approval Required: {ticket.action_type}",
                            },
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": "Ticket ID", "value": ticket.ticket_id},
                                    {"title": "Risk Level", "value": ticket.risk_level},
                                    {"title": "Reason", "value": ticket.risk_reason},
                                    {"title": "Requestor", "value": ticket.requestor_id},
                                ],
                            },
                        ],
                        "actions": [
                            {
                                "type": "Action.OpenUrl",
                                "title": "View & Approve",
                                "url": f"ironcore://approvals/{ticket.ticket_id}",
                            }
                        ],
                    },
                }
            ],
        }

        if self._http is None:
            logger.warning(
                "[Teams] No HTTP client configured — skipping Teams notification "
                "for ticket %s", ticket.ticket_id
            )
            return

        headers = {"Content-Type": "application/json"}
        await self._http.post(self._cfg.webhook_url, headers=headers, json=card)
        logger.info("[Teams] Sent approval request for ticket %s", ticket.ticket_id)
