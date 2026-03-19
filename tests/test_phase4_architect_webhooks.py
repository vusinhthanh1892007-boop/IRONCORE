"""
tests/test_phase4_architect_webhooks.py
=========================================
Phase 4 — The Architect (IronCore V2)

Tests for WebhookServer:
  - HMAC signature verify pass/fail (GitHub, Stripe, Generic)
  - Replay attack detection and rejection
  - Rate limiting → 429 response
  - Valid webhook → accepted + background task fired
  - Disabled registration → rejected
  - Event history persisted after dispatch
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

from ironcore.webhooks.models import WebhookRegistration, WebhookSource
from ironcore.webhooks.server import (
    REPLAY_TTL_SECONDS,
    WebhookNotFoundError,
    WebhookRateLimitExceeded,
    WebhookReplayError,
    WebhookServer,
    WebhookSignatureError,
    _REPLAY_STORE,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_github_sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _make_generic_sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _make_stripe_sig(secret: str, body: bytes, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    signed = f"{ts}.".encode() + body
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


@pytest.fixture(autouse=True)
def _clear_replay_store():
    """Ensure the global replay store is empty before each test."""
    _REPLAY_STORE.clear()
    yield
    _REPLAY_STORE.clear()


@pytest.fixture()
def server() -> WebhookServer:
    return WebhookServer(rate_limit_per_min=10)


@pytest.fixture()
def github_reg(server: WebhookServer) -> WebhookRegistration:
    reg = WebhookRegistration(
        name="Test GitHub",
        source=WebhookSource.GITHUB,
        endpoint_suffix="test-github",
        target_actions=["summarise_pr"],
        secret="github-secret-123",
    )
    server.register(reg)
    return reg


@pytest.fixture()
def stripe_reg(server: WebhookServer) -> WebhookRegistration:
    reg = WebhookRegistration(
        name="Test Stripe",
        source=WebhookSource.STRIPE,
        endpoint_suffix="test-stripe",
        target_actions=["upgrade_plan"],
        secret="stripe-secret-456",
    )
    server.register(reg)
    return reg


@pytest.fixture()
def custom_reg(server: WebhookServer) -> WebhookRegistration:
    reg = WebhookRegistration(
        name="Test Custom",
        source=WebhookSource.CUSTOM,
        endpoint_suffix="test-custom",
        target_actions=[],
        secret="custom-secret-789",
    )
    server.register(reg)
    return reg


# ─── GitHub HMAC ─────────────────────────────────────────────────────────────


def test_github_signature_valid(server, github_reg):
    body = b'{"action": "opened"}'
    sig = _make_github_sig(github_reg.secret, body)
    assert server.verify_github_signature(body, sig, github_reg.secret) is True


def test_github_signature_invalid(server, github_reg):
    body = b'{"action": "opened"}'
    sig = _make_github_sig("wrong-secret", body)
    assert server.verify_github_signature(body, sig, github_reg.secret) is False


def test_github_signature_missing_prefix(server, github_reg):
    body = b'{"action": "opened"}'
    # Without sha256= prefix
    raw_hex = hmac.new(github_reg.secret.encode(), body, hashlib.sha256).hexdigest()
    assert server.verify_github_signature(body, raw_hex, github_reg.secret) is False


# ─── Stripe HMAC ─────────────────────────────────────────────────────────────


def test_stripe_signature_valid(server, stripe_reg):
    body = b'{"type": "payment_intent.succeeded"}'
    sig = _make_stripe_sig(stripe_reg.secret, body)
    assert server.verify_stripe_signature(body, sig, stripe_reg.secret) is True


def test_stripe_signature_invalid_secret(server, stripe_reg):
    body = b'{"type": "payment_intent.succeeded"}'
    sig = _make_stripe_sig("wrong-stripe-secret", body)
    assert server.verify_stripe_signature(body, sig, stripe_reg.secret) is False


def test_stripe_signature_stale_timestamp(server, stripe_reg):
    """Timestamp more than 300 s old should fail."""
    body = b'{"type": "charge.succeeded"}'
    old_ts = int(time.time()) - 400
    sig = _make_stripe_sig(stripe_reg.secret, body, ts=old_ts)
    assert server.verify_stripe_signature(body, sig, stripe_reg.secret) is False


def test_stripe_signature_malformed(server, stripe_reg):
    body = b'{"type": "charge.succeeded"}'
    assert server.verify_stripe_signature(body, "not-a-real-sig", stripe_reg.secret) is False


# ─── Generic HMAC ─────────────────────────────────────────────────────────────


def test_generic_signature_valid(server, custom_reg):
    body = b'{"event_type": "deploy.done"}'
    sig = _make_generic_sig(custom_reg.secret, body)
    assert server.verify_generic_hmac(body, sig, custom_reg.secret) is True


def test_generic_signature_invalid(server, custom_reg):
    body = b'{"event_type": "deploy.done"}'
    sig = _make_generic_sig("wrong", body)
    assert server.verify_generic_hmac(body, sig, custom_reg.secret) is False


# ─── Replay protection ────────────────────────────────────────────────────────


def test_replay_first_delivery_allowed(server):
    assert server._check_replay("delivery-abc123") is False


def test_replay_second_delivery_blocked(server):
    server._check_replay("delivery-dup")
    assert server._check_replay("delivery-dup") is True


def test_replay_expired_entry_allowed(server):
    """Entries older than REPLAY_TTL_SECONDS should be pruned and allowed again."""
    delivery_id = "delivery-old"
    # Inject an expired entry directly
    _REPLAY_STORE[delivery_id] = time.time() - REPLAY_TTL_SECONDS - 1
    # Should be treated as new (expired)
    assert server._check_replay(delivery_id) is False


# ─── Rate limiting ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rate_limit_exceeded(server, custom_reg):
    """After rate_limit_per_min requests from same IP, the next one is rejected."""
    body = b'{"event_type": "ping"}'
    sig = _make_generic_sig(custom_reg.secret, body)
    headers = {
        "x-webhook-signature": sig,
        "x-webhook-delivery-id": None,
    }

    # Exhaust limit (10 for this fixture's server)
    for i in range(10):
        unique_headers = {
            "x-webhook-signature": _make_generic_sig(custom_reg.secret, body),
        }
        await server.handle_webhook(
            registration_id=custom_reg.id,
            raw_body=body,
            headers=unique_headers,
            client_ip="192.168.1.1",
        )
        # small sleep to ensure tasks don't overlap weirdly
        await asyncio.sleep(0)

    # The 11th call should raise
    with pytest.raises(WebhookRateLimitExceeded):
        await server.handle_webhook(
            registration_id=custom_reg.id,
            raw_body=body,
            headers={"x-webhook-signature": _make_generic_sig(custom_reg.secret, body)},
            client_ip="192.168.1.1",
        )


# ─── Valid event → accepted ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_github_webhook_accepted(server, github_reg):
    body = json.dumps({"action": "opened", "pull_request": {"title": "Fix bug"}}).encode()
    sig = _make_github_sig(github_reg.secret, body)
    headers = {
        "x-hub-signature-256": sig,
        "x-github-event": "pull_request",
        "x-github-delivery": "delivery-unique-001",
    }
    result = await server.handle_webhook(
        registration_id=github_reg.id,
        raw_body=body,
        headers=headers,
        client_ip="10.0.0.1",
    )
    assert result["status"] == "accepted"
    assert "event_id" in result


@pytest.mark.asyncio
async def test_valid_event_fires_dispatcher(server):
    """A custom action_dispatcher should be called for valid events."""
    dispatched: List = []

    async def my_dispatcher(event):
        dispatched.append(event)

    srv = WebhookServer(rate_limit_per_min=100, action_dispatcher=my_dispatcher)
    reg = WebhookRegistration(
        name="Dispatcher Test",
        source=WebhookSource.CUSTOM,
        endpoint_suffix="disp-test",
        secret="disp-secret",
    )
    srv.register(reg)

    body = b'{"event_type": "test.fired"}'
    sig = _make_generic_sig(reg.secret, body)
    await srv.handle_webhook(
        registration_id=reg.id,
        raw_body=body,
        headers={"x-webhook-signature": sig},
        client_ip="127.0.0.1",
    )
    # Let background task run
    await asyncio.sleep(0.05)
    assert len(dispatched) == 1
    assert dispatched[0].event_type == "test.fired"


# ─── Replay in full flow ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replay_rejected_in_full_flow(server, github_reg):
    body = b'{"action": "opened"}'
    sig = _make_github_sig(github_reg.secret, body)
    headers = {
        "x-hub-signature-256": sig,
        "x-github-event": "push",
        "x-github-delivery": "delivery-replay-test",
    }
    # First call: accepted
    await server.handle_webhook(
        registration_id=github_reg.id,
        raw_body=body,
        headers=headers,
        client_ip="10.0.0.2",
    )
    # Second call with same delivery_id: replay rejected
    with pytest.raises(WebhookReplayError):
        await server.handle_webhook(
            registration_id=github_reg.id,
            raw_body=body,
            headers=headers,
            client_ip="10.0.0.2",
        )


# ─── Invalid signature in full flow ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_signature_rejected(server, github_reg):
    body = b'{"action": "opened"}'
    bad_sig = _make_github_sig("wrong-secret", body)
    headers = {
        "x-hub-signature-256": bad_sig,
        "x-github-event": "push",
        "x-github-delivery": "delivery-sig-fail",
    }
    with pytest.raises(WebhookSignatureError):
        await server.handle_webhook(
            registration_id=github_reg.id,
            raw_body=body,
            headers=headers,
            client_ip="10.0.0.3",
        )


@pytest.mark.asyncio
async def test_missing_signature_header_rejected(server, github_reg):
    body = b'{"action": "opened"}'
    with pytest.raises(WebhookSignatureError, match="Missing signature header"):
        await server.handle_webhook(
            registration_id=github_reg.id,
            raw_body=body,
            headers={},
            client_ip="10.0.0.4",
        )


# ─── Disabled registration ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_registration_rejected(server, custom_reg):
    custom_reg.enabled = False
    body = b'{"event_type": "test"}'
    with pytest.raises(WebhookNotFoundError):
        await server.handle_webhook(
            registration_id=custom_reg.id,
            raw_body=body,
            headers={},
            client_ip="10.0.0.5",
        )
    # Re-enable for cleanup
    custom_reg.enabled = True


# ─── Event history ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_history_recorded(server, custom_reg):
    body = b'{"event_type": "history-check"}'
    sig = _make_generic_sig(custom_reg.secret, body)
    await server.handle_webhook(
        registration_id=custom_reg.id,
        raw_body=body,
        headers={"x-webhook-signature": sig},
        client_ip="10.0.0.6",
    )
    await asyncio.sleep(0.05)  # let background task run
    history = server.get_event_history(custom_reg.id)
    assert len(history) >= 1
    assert history[-1].event_type == "history-check"


# ─── Registration management ──────────────────────────────────────────────────


def test_register_duplicate_suffix_raises(server):
    reg_a = WebhookRegistration(
        name="A", source=WebhookSource.CUSTOM, endpoint_suffix="dup-suffix", secret="s1"
    )
    reg_b = WebhookRegistration(
        name="B", source=WebhookSource.GITHUB, endpoint_suffix="dup-suffix", secret="s2"
    )
    server.register(reg_a)
    with pytest.raises(ValueError, match="already in use"):
        server.register(reg_b)


def test_unregister_clears_suffix(server):
    reg = WebhookRegistration(
        name="Temp", source=WebhookSource.CUSTOM, endpoint_suffix="temp-suffix", secret="s"
    )
    server.register(reg)
    assert server.get_registration_by_suffix("temp-suffix") is not None
    server.unregister(reg.id)
    assert server.get_registration_by_suffix("temp-suffix") is None
    assert server.get_registration(reg.id) is None


def test_list_registrations(server, github_reg, stripe_reg):
    all_regs = server.list_registrations()
    ids = {r.id for r in all_regs}
    assert github_reg.id in ids
    assert stripe_reg.id in ids


# ─── Verify-signature=False skips HMAC ──────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_signature_false_skips_hmac(server):
    """When verify_signature=False, any body is accepted without checking sig."""
    reg = WebhookRegistration(
        name="No Verify",
        source=WebhookSource.CUSTOM,
        endpoint_suffix="no-verify",
        secret="irrelevant",
        verify_signature=False,
    )
    server.register(reg)
    result = await server.handle_webhook(
        registration_id=reg.id,
        raw_body=b'{"event_type": "open"}',
        headers={},
        client_ip="127.0.0.1",
    )
    assert result["status"] == "accepted"
