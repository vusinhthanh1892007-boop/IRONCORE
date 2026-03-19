"""Phase 9 — Enterprise HITL / Maker-Checker — Test Suite.

All tests are self-contained: no network calls, no Redis.
In-memory backend is used (redis_client=None).
"""

from __future__ import annotations

import asyncio
import hmac
import hashlib
import os
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ["IRONCORE_EDITION"] = "enterprise"

from ironcore.enterprise.hitl.models import (
    ApprovalRejectedError,
    ApprovalStatus,
    ApprovalTicket,
    ApprovalTimeoutError,
)
from ironcore.enterprise.hitl.engine import MakerCheckerEngine, _make_signature
from ironcore.enterprise.hitl.notifiers import (
    JiraConfig,
    JiraNotifier,
    SlackConfig,
    SlackNotifier,
    TeamsConfig,
    TeamsNotifier,
)


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _engine(**kw) -> MakerCheckerEngine:
    defaults = dict(redis_client=None, approval_timeout_hours=24)
    defaults.update(kw)
    return MakerCheckerEngine(**defaults)


async def _make_ticket(engine: MakerCheckerEngine, **overrides) -> ApprovalTicket:
    defaults = dict(
        session_id="sess-001",
        action_type="update_credit_limit",
        action_payload={"customer": "A", "old_limit": "50M", "new_limit": "500M"},
        risk_reason="Financial change exceeds threshold",
        approver_ids=["manager@bank.com"],
    )
    defaults.update(overrides)
    return await engine.request_approval(**defaults)


# ══════════════════════════════════════════════════════════════════════════════
#  TestApprovalTicket (model)
# ══════════════════════════════════════════════════════════════════════════════

class TestApprovalTicket:
    def test_ticket_id_format(self) -> None:
        t = ApprovalTicket(
            session_id="s1",
            action_type="test",
            action_payload={},
            risk_level="CRITICAL",
            risk_reason="test",
            requestor_id="ai",
            approver_ids=["mgr@bank.com"],
        )
        assert t.ticket_id.startswith("IRON-")
        assert len(t.ticket_id) == len("IRON-") + 12  # 6 bytes hex = 12 chars

    def test_default_status_pending(self) -> None:
        t = ApprovalTicket(
            session_id="s1",
            action_type="x",
            action_payload={},
            risk_level="CRITICAL",
            risk_reason="r",
            requestor_id="ai",
            approver_ids=["m@b.com"],
        )
        assert t.status == ApprovalStatus.PENDING

    def test_expires_at_24h_after_created(self) -> None:
        before = time.time()
        t = ApprovalTicket(
            session_id="s1",
            action_type="x",
            action_payload={},
            risk_level="CRITICAL",
            risk_reason="r",
            requestor_id="ai",
            approver_ids=["m@b.com"],
        )
        assert abs(t.expires_at - (t.created_at + 86_400)) < 1

    def test_is_expired_false_when_fresh(self) -> None:
        t = ApprovalTicket(
            session_id="s",
            action_type="x",
            action_payload={},
            risk_level="CRITICAL",
            risk_reason="r",
            requestor_id="ai",
            approver_ids=["m@b.com"],
            expires_at=time.time() + 3600,
        )
        assert t.is_expired is False

    def test_is_expired_true_when_past(self) -> None:
        t = ApprovalTicket(
            session_id="s",
            action_type="x",
            action_payload={},
            risk_level="CRITICAL",
            risk_reason="r",
            requestor_id="ai",
            approver_ids=["m@b.com"],
            expires_at=time.time() - 1,
        )
        assert t.is_expired is True

    def test_is_terminal_pending_false(self) -> None:
        t = ApprovalTicket(
            session_id="s",
            action_type="x",
            action_payload={},
            risk_level="CRITICAL",
            risk_reason="r",
            requestor_id="ai",
            approver_ids=["m@b.com"],
        )
        assert t.is_terminal is False

    def test_is_terminal_approved_true(self) -> None:
        t = ApprovalTicket(
            session_id="s",
            action_type="x",
            action_payload={},
            risk_level="CRITICAL",
            risk_reason="r",
            requestor_id="ai",
            approver_ids=["m@b.com"],
            status=ApprovalStatus.APPROVED,
        )
        assert t.is_terminal is True

    def test_unique_ticket_ids(self) -> None:
        ids = {
            ApprovalTicket(
                session_id="s",
                action_type="x",
                action_payload={},
                risk_level="CRITICAL",
                risk_reason="r",
                requestor_id="ai",
                approver_ids=["m@b.com"],
            ).ticket_id
            for _ in range(20)
        }
        assert len(ids) == 20, "Duplicate ticket IDs found!"


# ══════════════════════════════════════════════════════════════════════════════
#  TestMakerCheckerEngine — request / approve / reject
# ══════════════════════════════════════════════════════════════════════════════

class TestMakerCheckerEngine:
    @pytest.mark.asyncio
    async def test_request_approval_returns_pending_ticket(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e)
        assert ticket.status == ApprovalStatus.PENDING
        assert ticket.ticket_id.startswith("IRON-")

    @pytest.mark.asyncio
    async def test_request_approval_persists_ticket(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e)
        loaded = await e.get_ticket(ticket.ticket_id)
        assert loaded is not None
        assert loaded.ticket_id == ticket.ticket_id

    @pytest.mark.asyncio
    async def test_approve_ticket(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e)
        approved = await e.approve(
            ticket.ticket_id,
            approver_id="manager@bank.com",
            approver_session_key="secret-key",
        )
        assert approved.status == ApprovalStatus.APPROVED
        assert approved.approved_by == "manager@bank.com"
        assert approved.approved_at is not None

    @pytest.mark.asyncio
    async def test_approve_sets_digital_signature(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e)
        approved = await e.approve(
            ticket.ticket_id,
            approver_id="manager@bank.com",
            approver_session_key="my-secret",
        )
        assert approved.digital_signature is not None
        assert len(approved.digital_signature) == 64  # SHA256 hex = 64 chars

    @pytest.mark.asyncio
    async def test_digital_signature_verifiable(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e)
        session_key = "my-secret"
        approved = await e.approve(
            ticket.ticket_id,
            approver_id="manager@bank.com",
            approver_session_key=session_key,
        )
        expected = _make_signature(
            ticket.ticket_id, "manager@bank.com", approved.approved_at, session_key
        )
        assert approved.digital_signature == expected

    @pytest.mark.asyncio
    async def test_reject_ticket(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e)
        rejected = await e.reject(
            ticket.ticket_id,
            approver_id="manager@bank.com",
            reason="Exceeds policy limit",
        )
        assert rejected.status == ApprovalStatus.REJECTED
        assert rejected.rejection_reason == "Exceeds policy limit"

    @pytest.mark.asyncio
    async def test_approve_non_allowlisted_approver_raises(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e, approver_ids=["mgr@bank.com"])
        with pytest.raises(ValueError, match="not in the approver allowlist"):
            await e.approve(ticket.ticket_id, "hacker@evil.com", "bad-key")

    @pytest.mark.asyncio
    async def test_reject_non_allowlisted_approver_raises(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e, approver_ids=["mgr@bank.com"])
        with pytest.raises(ValueError, match="not in the approver allowlist"):
            await e.reject(ticket.ticket_id, "hacker@evil.com", "reason")

    @pytest.mark.asyncio
    async def test_double_approve_raises(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e)
        await e.approve(ticket.ticket_id, "manager@bank.com", "key")
        with pytest.raises(ValueError, match="already in terminal state"):
            await e.approve(ticket.ticket_id, "manager@bank.com", "key")

    @pytest.mark.asyncio
    async def test_approve_after_reject_raises(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e)
        await e.reject(ticket.ticket_id, "manager@bank.com", "no")
        with pytest.raises(ValueError, match="already in terminal state"):
            await e.approve(ticket.ticket_id, "manager@bank.com", "key")

    @pytest.mark.asyncio
    async def test_approve_unknown_ticket_raises(self) -> None:
        e = _engine()
        with pytest.raises(ValueError, match="not found"):
            await e.approve("IRON-DEADBEEF", "mgr@bank.com", "key")

    @pytest.mark.asyncio
    async def test_reject_unknown_ticket_raises(self) -> None:
        e = _engine()
        with pytest.raises(ValueError, match="not found"):
            await e.reject("IRON-DEADBEEF", "mgr@bank.com", "reason")


# ══════════════════════════════════════════════════════════════════════════════
#  TestMakerCheckerEngine — revoke
# ══════════════════════════════════════════════════════════════════════════════

class TestRevoke:
    @pytest.mark.asyncio
    async def test_revoke_approved_ticket(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e)
        await e.approve(ticket.ticket_id, "manager@bank.com", "key")
        revoked = await e.revoke(ticket.ticket_id, "compliance@bank.com", "Error found")
        assert revoked.status == ApprovalStatus.REVOKED
        assert "Error found" in revoked.rejection_reason

    @pytest.mark.asyncio
    async def test_revoke_pending_ticket_raises(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e)
        with pytest.raises(ValueError, match="Only APPROVED tickets can be revoked"):
            await e.revoke(ticket.ticket_id, "compliance@bank.com", "reason")

    @pytest.mark.asyncio
    async def test_revoke_rejected_ticket_raises(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e)
        await e.reject(ticket.ticket_id, "manager@bank.com", "no")
        with pytest.raises(ValueError, match="Only APPROVED tickets can be revoked"):
            await e.revoke(ticket.ticket_id, "compliance@bank.com", "reason")


# ══════════════════════════════════════════════════════════════════════════════
#  TestWaitForApproval
# ══════════════════════════════════════════════════════════════════════════════

class TestWaitForApproval:
    @pytest.mark.asyncio
    async def test_wait_resolves_immediately_if_already_approved(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e)
        await e.approve(ticket.ticket_id, "manager@bank.com", "key")
        result = await e.wait_for_approval(ticket.ticket_id, poll_interval=0.01)
        assert result.status == ApprovalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_wait_raises_on_expired_ticket(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e)
        # Manually expire the ticket
        ticket.expires_at = time.time() - 1
        await e._save(ticket)
        with pytest.raises(ApprovalTimeoutError) as exc_info:
            await e.wait_for_approval(ticket.ticket_id, poll_interval=0.01)
        assert exc_info.value.ticket_id == ticket.ticket_id

    @pytest.mark.asyncio
    async def test_wait_raises_on_missing_ticket(self) -> None:
        e = _engine()
        with pytest.raises(ApprovalTimeoutError):
            await e.wait_for_approval("IRON-NONEXISTENT", poll_interval=0.01)

    @pytest.mark.asyncio
    async def test_wait_polls_until_approved(self) -> None:
        """Approve the ticket from a concurrent task while wait_for_approval is polling."""
        e = _engine()
        ticket = await _make_ticket(e)

        async def _approve_later():
            await asyncio.sleep(0.05)
            await e.approve(ticket.ticket_id, "manager@bank.com", "key")

        result, _ = await asyncio.gather(
            e.wait_for_approval(ticket.ticket_id, poll_interval=0.01),
            _approve_later(),
        )
        assert result.status == ApprovalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_wait_resolves_on_rejection(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e)

        async def _reject_later():
            await asyncio.sleep(0.05)
            await e.reject(ticket.ticket_id, "manager@bank.com", "no budget")

        result, _ = await asyncio.gather(
            e.wait_for_approval(ticket.ticket_id, poll_interval=0.01),
            _reject_later(),
        )
        assert result.status == ApprovalStatus.REJECTED


# ══════════════════════════════════════════════════════════════════════════════
#  TestEditionGuard
# ══════════════════════════════════════════════════════════════════════════════

class TestEditionGuard:
    def test_community_edition_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_EDITION", "community")
        with pytest.raises(RuntimeError, match="Enterprise"):
            MakerCheckerEngine()
        monkeypatch.setenv("IRONCORE_EDITION", "enterprise")

    def test_enterprise_edition_ok(self) -> None:
        engine = _engine()
        assert engine is not None


# ══════════════════════════════════════════════════════════════════════════════
#  TestFromEnv
# ══════════════════════════════════════════════════════════════════════════════

class TestFromEnv:
    def test_from_env_timeout_hours(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_APPROVAL_TIMEOUT_HOURS", "48")
        e = MakerCheckerEngine.from_env()
        assert e._approval_timeout_hours == 48

    def test_from_env_no_notifiers_when_no_env(self, monkeypatch) -> None:
        for key in ("IRONCORE_JIRA_URL", "IRONCORE_JIRA_TOKEN", "IRONCORE_SLACK_BOT_TOKEN",
                    "IRONCORE_TEAMS_WEBHOOK_URL"):
            monkeypatch.delenv(key, raising=False)
        e = MakerCheckerEngine.from_env()
        assert e._jira is None
        assert e._slack is None
        assert e._teams is None

    def test_from_env_jira_config_created(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_JIRA_URL", "https://bank.atlassian.net")
        monkeypatch.setenv("IRONCORE_JIRA_TOKEN", "tok")
        monkeypatch.setenv("IRONCORE_JIRA_PROJECT", "MYPROJ")
        e = MakerCheckerEngine.from_env()
        assert e._jira is not None
        assert e._jira._cfg.project_key == "MYPROJ"

    def test_from_env_slack_config_created(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_SLACK_BOT_TOKEN", "xoxb-1234")
        monkeypatch.setenv("IRONCORE_SLACK_APPROVAL_CHANNEL", "#custom-channel")
        e = MakerCheckerEngine.from_env()
        assert e._slack is not None
        assert e._slack._cfg.channel == "#custom-channel"

    def test_from_env_teams_config_created(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_TEAMS_WEBHOOK_URL", "https://webhook.office.com/abc")
        e = MakerCheckerEngine.from_env()
        assert e._teams is not None


# ══════════════════════════════════════════════════════════════════════════════
#  TestJiraNotifier
# ══════════════════════════════════════════════════════════════════════════════

class TestJiraNotifier:
    @pytest.mark.asyncio
    async def test_create_issue_returns_mock_key_when_no_client(self) -> None:
        cfg = JiraConfig(base_url="https://jira.example.com", token="tok")
        notifier = JiraNotifier(cfg, http_client=None)
        ticket = ApprovalTicket(
            session_id="s",
            action_type="transfer",
            action_payload={},
            risk_level="CRITICAL",
            risk_reason="r",
            requestor_id="ai",
            approver_ids=["m@b.com"],
        )
        key = await notifier.create_issue(ticket)
        assert key.endswith("-MOCK")

    @pytest.mark.asyncio
    async def test_create_issue_uses_http_client(self) -> None:
        cfg = JiraConfig(base_url="https://jira.example.com", token="tok")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"key": "IRON-9821"}
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_resp)

        notifier = JiraNotifier(cfg, http_client=mock_http)
        ticket = ApprovalTicket(
            session_id="s",
            action_type="update_limit",
            action_payload={},
            risk_level="CRITICAL",
            risk_reason="r",
            requestor_id="ai",
            approver_ids=["m@b.com"],
        )
        key = await notifier.create_issue(ticket)
        assert key == "IRON-9821"
        mock_http.post.assert_awaited_once()


# ══════════════════════════════════════════════════════════════════════════════
#  TestSlackNotifier
# ══════════════════════════════════════════════════════════════════════════════

class TestSlackNotifier:
    @pytest.mark.asyncio
    async def test_send_returns_mock_ts_when_no_client(self) -> None:
        cfg = SlackConfig(bot_token="xoxb-fake")
        notifier = SlackNotifier(cfg, http_client=None)
        ticket = ApprovalTicket(
            session_id="s",
            action_type="delete_data",
            action_payload={},
            risk_level="CRITICAL",
            risk_reason="r",
            requestor_id="ai",
            approver_ids=["m@b.com"],
        )
        ts = await notifier.send_approval_request(ticket)
        assert ts.startswith("mock-ts-")

    @pytest.mark.asyncio
    async def test_send_uses_http_client(self) -> None:
        cfg = SlackConfig(bot_token="xoxb-fake")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "ts": "1700000000.111222"}
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_resp)

        notifier = SlackNotifier(cfg, http_client=mock_http)
        ticket = ApprovalTicket(
            session_id="s",
            action_type="delete_data",
            action_payload={},
            risk_level="CRITICAL",
            risk_reason="r",
            requestor_id="ai",
            approver_ids=["m@b.com"],
        )
        ts = await notifier.send_approval_request(ticket)
        assert ts == "1700000000.111222"
        mock_http.post.assert_awaited_once()


# ══════════════════════════════════════════════════════════════════════════════
#  TestTeamsNotifier
# ══════════════════════════════════════════════════════════════════════════════

class TestTeamsNotifier:
    @pytest.mark.asyncio
    async def test_send_noop_when_no_client(self) -> None:
        cfg = TeamsConfig(webhook_url="https://webhook.office.com/abc")
        notifier = TeamsNotifier(cfg, http_client=None)
        ticket = ApprovalTicket(
            session_id="s",
            action_type="mass_update",
            action_payload={},
            risk_level="CRITICAL",
            risk_reason="r",
            requestor_id="ai",
            approver_ids=["m@b.com"],
        )
        # Should not raise
        await notifier.send_approval_request(ticket)

    @pytest.mark.asyncio
    async def test_send_uses_http_client(self) -> None:
        cfg = TeamsConfig(webhook_url="https://webhook.office.com/abc")
        mock_http = MagicMock()
        mock_http.post = AsyncMock()

        notifier = TeamsNotifier(cfg, http_client=mock_http)
        ticket = ApprovalTicket(
            session_id="s",
            action_type="mass_update",
            action_payload={},
            risk_level="CRITICAL",
            risk_reason="r",
            requestor_id="ai",
            approver_ids=["m@b.com"],
        )
        await notifier.send_approval_request(ticket)
        mock_http.post.assert_awaited_once_with(
            cfg.webhook_url, headers={"Content-Type": "application/json"}, json=mock_http.post.call_args.kwargs["json"]
        )


# ══════════════════════════════════════════════════════════════════════════════
#  TestNotificationIntegration (engine calls notifiers)
# ══════════════════════════════════════════════════════════════════════════════

class TestNotificationIntegration:
    @pytest.mark.asyncio
    async def test_jira_issue_key_saved_on_ticket(self) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"key": "IRON-5555"}
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_resp)

        jira_cfg = JiraConfig(base_url="https://jira.example.com", token="tok")
        e = MakerCheckerEngine(redis_client=None, jira_config=jira_cfg, http_client=mock_http)
        ticket = await _make_ticket(e)
        assert ticket.jira_issue_key == "IRON-5555"

    @pytest.mark.asyncio
    async def test_slack_ts_saved_on_ticket(self) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "ts": "111.222"}
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_resp)

        slack_cfg = SlackConfig(bot_token="xoxb-fake")
        e = MakerCheckerEngine(redis_client=None, slack_config=slack_cfg, http_client=mock_http)
        ticket = await _make_ticket(e)
        assert ticket.slack_message_ts == "111.222"

    @pytest.mark.asyncio
    async def test_notifier_failure_does_not_prevent_ticket_creation(self) -> None:
        """Even if Jira / Slack raise, the ticket is still created."""
        mock_http = MagicMock()
        mock_http.post = AsyncMock(side_effect=ConnectionError("Jira down"))

        jira_cfg = JiraConfig(base_url="https://jira.example.com", token="tok")
        e = MakerCheckerEngine(redis_client=None, jira_config=jira_cfg, http_client=mock_http)
        ticket = await _make_ticket(e)
        assert ticket.status == ApprovalStatus.PENDING  # ticket still created


# ══════════════════════════════════════════════════════════════════════════════
#  TestDigitalSignature
# ══════════════════════════════════════════════════════════════════════════════

class TestDigitalSignature:
    def test_signature_is_hmac_sha256(self) -> None:
        sig = _make_signature("IRON-ABCDEF123456", "mgr@bank.com", 1_700_000_000.0, "secret")
        # Verify manually with hmac
        message = f"IRON-ABCDEF123456:mgr@bank.com:{1_700_000_000.0:.6f}".encode()
        expected = hmac.new(b"secret", message, hashlib.sha256).hexdigest()
        assert sig == expected

    def test_different_keys_produce_different_sigs(self) -> None:
        s1 = _make_signature("T1", "m@b.com", 1.0, "key1")
        s2 = _make_signature("T1", "m@b.com", 1.0, "key2")
        assert s1 != s2

    def test_different_timestamps_produce_different_sigs(self) -> None:
        s1 = _make_signature("T1", "m@b.com", 1.0, "key")
        s2 = _make_signature("T1", "m@b.com", 2.0, "key")
        assert s1 != s2

    @pytest.mark.asyncio
    async def test_engine_approve_signature_verifiable(self) -> None:
        e = _engine()
        ticket = await _make_ticket(e)
        approved = await e.approve(ticket.ticket_id, "manager@bank.com", "sk")
        expected = _make_signature(
            ticket.ticket_id, "manager@bank.com", approved.approved_at, "sk"
        )
        assert approved.digital_signature == expected


# ══════════════════════════════════════════════════════════════════════════════
#  TestExceptions
# ══════════════════════════════════════════════════════════════════════════════

class TestExceptions:
    def test_timeout_error_has_ticket_id(self) -> None:
        err = ApprovalTimeoutError("IRON-DEADBEEF")
        assert err.ticket_id == "IRON-DEADBEEF"
        assert "IRON-DEADBEEF" in str(err)

    def test_rejected_error_has_attributes(self) -> None:
        err = ApprovalRejectedError("IRON-ABC", "mgr@bank.com", "No budget")
        assert err.ticket_id == "IRON-ABC"
        assert err.approver_id == "mgr@bank.com"
        assert err.reason == "No budget"
        assert "mgr@bank.com" in str(err)


# ══════════════════════════════════════════════════════════════════════════════
#  TestApprovalStatuses
# ══════════════════════════════════════════════════════════════════════════════

class TestApprovalStatuses:
    def test_all_statuses_are_strings(self) -> None:
        for status in ApprovalStatus:
            assert isinstance(status.value, str)

    def test_pending_is_not_terminal(self) -> None:
        t = ApprovalTicket(
            session_id="s",
            action_type="x",
            action_payload={},
            risk_level="CRITICAL",
            risk_reason="r",
            requestor_id="ai",
            approver_ids=["m@b.com"],
            status=ApprovalStatus.PENDING,
        )
        assert not t.is_terminal

    @pytest.mark.parametrize("status", [
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
        ApprovalStatus.REVOKED,
    ])
    def test_terminal_statuses(self, status: ApprovalStatus) -> None:
        t = ApprovalTicket(
            session_id="s",
            action_type="x",
            action_payload={},
            risk_level="CRITICAL",
            risk_reason="r",
            requestor_id="ai",
            approver_ids=["m@b.com"],
            status=status,
        )
        assert t.is_terminal
