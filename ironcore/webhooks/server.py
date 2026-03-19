"""
IronCore V2 — WebhookServer
=============================
Phase 4 — The Architect (Gemini 3.1)

Handles inbound webhook events from GitHub, Stripe, GitLab, and arbitrary
custom services.

Security properties enforced on every inbound request
------------------------------------------------------
1. HMAC-SHA256 signature verification via :func:`hmac.compare_digest`
   (constant-time — immune to timing oracle attacks).
2. Replay-attack prevention: delivery IDs stored in a TTL-based in-memory
   map; duplicates rejected for up to 1 hour.
3. Rate limiting (sliding window, 100 events/60 s per IP by default).
4. Background async processing: handler returns immediately after
   queuing the task — upstream sender is never made to wait.

No external Redis dependency is required; all state is in-process.
A Redis client can optionally be injected for distributed deployments
(future extension point, interface left open).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict
from typing import Any, Callable, DefaultDict, Dict, List, Optional

from ironcore.webhooks.models import WebhookEvent, WebhookRegistration, WebhookSource

logger = logging.getLogger(__name__)

# ─── Replay protection store ─────────────────────────────────────────────────
# Maps delivery_id → received_at timestamp.
# Delivery IDs are retained for REPLAY_TTL_SECONDS; older entries are pruned
# lazily on each check to avoid unbounded memory growth.
_REPLAY_STORE: Dict[str, float] = {}
REPLAY_TTL_SECONDS: float = 3600.0  # 1 hour


class WebhookRateLimitExceeded(Exception):
    """Raised when an IP address exceeds the per-minute rate limit."""


class WebhookSignatureError(Exception):
    """Raised when HMAC verification fails or the signature header is absent."""


class WebhookReplayError(Exception):
    """Raised when a duplicate delivery ID is detected (replay attack)."""


class WebhookNotFoundError(Exception):
    """Raised when no registration matches the requested endpoint suffix."""


# ─── Sliding-window rate limiter (per IP, in-process) ─────────────────────────

class _IPRateLimiter:
    def __init__(self, limit: int = 100, window: float = 60.0) -> None:
        self._limit = limit
        self._window = window
        self._calls: DefaultDict[str, List[float]] = defaultdict(list)

    def check(self, ip: str) -> bool:
        """Return True if the IP is within its rate limit window."""
        now = time.time()
        window_start = now - self._window
        active = [t for t in self._calls[ip] if t > window_start]
        self._calls[ip] = active
        if len(active) >= self._limit:
            return False
        active.append(now)
        return True


# ─── WebhookServer ────────────────────────────────────────────────────────────

class WebhookServer:
    """
    Manages webhook registrations and processes inbound events.

    Parameters
    ----------
    rate_limit_per_min:
        Maximum webhook events accepted per IP per 60-second window.
    action_dispatcher:
        Optional async callable invoked with every successfully parsed
        WebhookEvent.  Signature: ``async def dispatch(event: WebhookEvent) → None``.
        When *None*, events are logged at INFO level but not acted upon.
    """

    def __init__(
        self,
        rate_limit_per_min: int = 100,
        action_dispatcher: Optional[Callable[[WebhookEvent], Any]] = None,
    ) -> None:
        # Registrations keyed by registration.id and also by endpoint_suffix for O(1) routing
        self._by_id: Dict[str, WebhookRegistration] = {}
        self._by_suffix: Dict[str, WebhookRegistration] = {}
        # Event history (last 1 000 events per registration, ring-buffer style)
        self._history: DefaultDict[str, List[WebhookEvent]] = defaultdict(list)
        self._history_limit = 1_000
        self._rate_limiter = _IPRateLimiter(limit=rate_limit_per_min)
        self._dispatcher = action_dispatcher

    # ── Registration management ──────────────────────────────────────────────

    def register(self, reg: WebhookRegistration) -> WebhookRegistration:
        """
        Add a new webhook registration.

        Raises ValueError if *endpoint_suffix* is already taken.
        """
        if reg.endpoint_suffix in self._by_suffix:
            existing = self._by_suffix[reg.endpoint_suffix]
            if existing.id != reg.id:
                raise ValueError(
                    f"Endpoint suffix '{reg.endpoint_suffix}' is already in use "
                    f"by registration '{existing.id}'."
                )
        self._by_id[reg.id] = reg
        self._by_suffix[reg.endpoint_suffix] = reg
        logger.info(
            "[WebhookServer] Registered id=%s source=%s suffix=%s",
            reg.id, reg.source.value, reg.endpoint_suffix,
        )
        return reg

    def unregister(self, registration_id: str) -> None:
        """Remove a registration.  Silently ignores unknown IDs."""
        reg = self._by_id.pop(registration_id, None)
        if reg:
            self._by_suffix.pop(reg.endpoint_suffix, None)
            logger.info("[WebhookServer] Unregistered id=%s", registration_id)

    def get_registration(self, registration_id: str) -> Optional[WebhookRegistration]:
        return self._by_id.get(registration_id)

    def get_registration_by_suffix(self, suffix: str) -> Optional[WebhookRegistration]:
        return self._by_suffix.get(suffix)

    def list_registrations(self) -> List[WebhookRegistration]:
        return list(self._by_id.values())

    def get_event_history(self, registration_id: str) -> List[WebhookEvent]:
        return list(self._history[registration_id])

    # ── HMAC verification ───────────────────────────────────────────────────

    def verify_github_signature(
        self, payload: bytes, signature_header: str, secret: str
    ) -> bool:
        """
        Verify the ``X-Hub-Signature-256`` header sent by GitHub.

        Uses :func:`hmac.compare_digest` (constant-time) to prevent
        timing-oracle attacks.  Returns False rather than raising so that
        callers can decide the appropriate HTTP response.
        """
        if not signature_header.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    def verify_stripe_signature(
        self, payload: bytes, signature_header: str, secret: str
    ) -> bool:
        """
        Verify ``Stripe-Signature`` using Stripe's timestamp+payload scheme.

        Format: ``t=<ts>,v1=<sig>[,v1=<sig>...]``
        Validates that *now − t < 300 s* to prevent replay attacks
        in addition to signature correctness.
        """
        try:
            parts: Dict[str, str] = {}
            for item in signature_header.split(","):
                k, _, v = item.partition("=")
                parts[k.strip()] = v.strip()
            timestamp = parts.get("t", "")
            v1_sig = parts.get("v1", "")
            if not timestamp or not v1_sig:
                return False
            # Timestamp freshness check (±5 minutes)
            if abs(time.time() - float(timestamp)) > 300:
                return False
            signed_payload = f"{timestamp}.".encode() + payload
            expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, v1_sig)
        except Exception:
            return False

    def verify_generic_hmac(
        self, payload: bytes, signature_header: str, secret: str
    ) -> bool:
        """
        Generic HMAC-SHA256 check — ``X-Webhook-Signature: sha256=<hex>``.
        Same constant-time comparison.
        """
        if not signature_header.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    # ── Replay-attack prevention ─────────────────────────────────────────────

    def _check_replay(self, delivery_id: str) -> bool:
        """
        Return True if *delivery_id* has been seen before (replay attack).

        Lazily prunes expired entries on each call to bound memory usage.
        """
        now = time.time()
        cutoff = now - REPLAY_TTL_SECONDS

        # Lazy pruning — only triggered on check, O(n) in the worst case but
        # bounded by actual event throughput.
        expired = [k for k, v in _REPLAY_STORE.items() if v < cutoff]
        for k in expired:
            del _REPLAY_STORE[k]

        if delivery_id in _REPLAY_STORE:
            return True  # Already seen
        _REPLAY_STORE[delivery_id] = now
        return False

    # ── Event dispatching ────────────────────────────────────────────────────

    async def _process_github_event(self, event: WebhookEvent) -> None:
        """Handle a GitHub webhook event after validation."""
        event_type = event.event_type
        payload = event.payload
        logger.info(
            "[WebhookServer] Processing GitHub event type=%s delivery=%s",
            event_type, event.delivery_id,
        )
        # PR opened / synchronize → summarise
        if event_type in ("pull_request",):
            pr = payload.get("pull_request", {})
            title = pr.get("title", "")
            action = payload.get("action", "")
            logger.info("[WebhookServer] PR action=%s title=%s", action, title)

        # Push to default branch → check OTA update
        elif event_type == "push":
            ref = payload.get("ref", "")
            logger.info("[WebhookServer] Push event ref=%s", ref)

    async def _process_stripe_event(self, event: WebhookEvent) -> None:
        """Handle a Stripe webhook event after validation."""
        logger.info(
            "[WebhookServer] Processing Stripe event type=%s id=%s",
            event.event_type, event.id,
        )
        if event.event_type == "payment_intent.succeeded":
            amount = event.payload.get("data", {}).get("object", {}).get("amount", 0)
            logger.info("[WebhookServer] Payment succeeded amount=%s", amount)

    async def _process_custom_event(self, event: WebhookEvent) -> None:
        """Handle a custom-source webhook event after validation."""
        logger.info(
            "[WebhookServer] Processing custom event type=%s", event.event_type
        )

    async def _dispatch_event(self, event: WebhookEvent) -> None:
        """Route event to the appropriate processor and optionally call user dispatcher."""
        try:
            if event.source == WebhookSource.GITHUB:
                await self._process_github_event(event)
            elif event.source == WebhookSource.STRIPE:
                await self._process_stripe_event(event)
            elif event.source in (WebhookSource.GITLAB, WebhookSource.CUSTOM):
                await self._process_custom_event(event)

            if self._dispatcher is not None:
                await self._dispatcher(event)

            event.processed = True
        except Exception as exc:
            event.error = str(exc)
            logger.error(
                "[WebhookServer] Error processing event id=%s: %s",
                event.id, exc, exc_info=True,
            )
        finally:
            # Persist into per-registration history (ring-buffer behaviour)
            history = self._history[event.registration_id]
            history.append(event)
            if len(history) > self._history_limit:
                history.pop(0)

    # ── Main entry point ─────────────────────────────────────────────────────

    async def handle_webhook(
        self,
        *,
        registration_id: str,
        raw_body: bytes,
        headers: Dict[str, str],
        client_ip: str = "unknown",
    ) -> Dict[str, Any]:
        """
        Primary webhook handler.

        1. Look up registration.
        2. Rate-limit by client IP.
        3. Verify HMAC signature (if *verify_signature* is True).
        4. Reject replay (if delivery ID present).
        5. Parse event type and payload.
        6. Fire-and-forget background task — returns ``{"status": "accepted"}``
           immediately so the upstream sender gets a quick 200/202 ACK.

        Raises
        ------
        WebhookNotFoundError
            Unknown registration ID.
        WebhookRateLimitExceeded
            Client IP has exceeded the rate limit.
        WebhookSignatureError
            Signature header is missing or invalid.
        WebhookReplayError
            Delivery ID has been seen before.
        """
        reg = self._by_id.get(registration_id)
        if reg is None or not reg.enabled:
            raise WebhookNotFoundError(f"Unknown or disabled registration: {registration_id}")

        # 2. Rate limit
        if not self._rate_limiter.check(client_ip):
            logger.warning(
                "[WebhookServer] Rate limit exceeded for ip=%s registration=%s",
                client_ip, registration_id,
            )
            raise WebhookRateLimitExceeded(
                f"Rate limit exceeded for IP {client_ip}. Try again in 60 seconds."
            )

        # 3. Signature verification
        if reg.verify_signature:
            sig_header = (
                headers.get("x-hub-signature-256")
                or headers.get("stripe-signature")
                or headers.get("x-webhook-signature")
                or ""
            )
            if not sig_header:
                raise WebhookSignatureError(
                    "Missing signature header. Expected X-Hub-Signature-256, "
                    "Stripe-Signature, or X-Webhook-Signature."
                )

            if reg.source == WebhookSource.GITHUB:
                valid = self.verify_github_signature(raw_body, sig_header, reg.secret)
            elif reg.source == WebhookSource.STRIPE:
                valid = self.verify_stripe_signature(raw_body, sig_header, reg.secret)
            else:
                valid = self.verify_generic_hmac(raw_body, sig_header, reg.secret)

            if not valid:
                logger.warning(
                    "[WebhookServer] Invalid signature for registration=%s ip=%s",
                    registration_id, client_ip,
                )
                raise WebhookSignatureError("HMAC signature verification failed.")

        # 4. Replay protection
        delivery_id = (
            headers.get("x-github-delivery")
            or headers.get("x-stripe-event-id")
            or headers.get("x-webhook-delivery-id")
        )
        if delivery_id:
            if self._check_replay(delivery_id):
                logger.warning(
                    "[WebhookServer] Replay detected delivery_id=%s registration=%s",
                    delivery_id, registration_id,
                )
                raise WebhookReplayError(
                    f"Duplicate delivery ID '{delivery_id}'. Replay attack rejected."
                )

        # 5. Parse event
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            body = {}

        # Determine event_type from headers or body
        event_type = (
            headers.get("x-github-event")
            or headers.get("x-gitlab-event")
            or body.get("type")            # Stripe uses body["type"]
            or body.get("event_type")
            or "unknown"
        )

        event = WebhookEvent(
            registration_id=registration_id,
            source=reg.source,
            event_type=event_type,
            delivery_id=delivery_id,
            payload=body,
        )

        # 6. Background processing — do NOT await here
        asyncio.create_task(self._dispatch_event(event))

        logger.info(
            "[WebhookServer] Accepted event_id=%s type=%s registration=%s ip=%s",
            event.id, event_type, registration_id, client_ip,
        )
        return {"status": "accepted", "event_id": event.id}
