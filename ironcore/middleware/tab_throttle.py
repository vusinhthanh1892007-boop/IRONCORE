"""
ironcore/middleware/tab_throttle.py
=====================================
Phase 14 — CE Tab Throttling (The Architect, IronCore V2)

Community Edition: enforce minimum delay between session-creation requests
per client (IP or authenticated user id).

Enterprise Edition: bypass completely (delay = 0.0 s).

The middleware sits *after* auth middleware so it can prefer user_id over IP,
but *before* routers.  It only applies to the endpoints listed in
``THROTTLED_PATHS`` — those that spawn a new agent session.  Regular
message/chat endpoints inside an existing session are NOT throttled.

Backend storage: any object that implements the async duck-type interface
  ``get(key) -> bytes | str | None``
  ``set(key, value, ex=<seconds>) -> None``

This matches the interface of ``redis.asyncio.Redis``, ``aioredis.Redis``,
and the built-in ``_InMemoryThrottleStore`` (used in tests / no-Redis setups).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ironcore.edition import is_enterprise

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoints that create a brand-new agent session.  Only these paths are
# subject to tab throttling; all other paths pass through freely.
# ---------------------------------------------------------------------------
THROTTLED_PATHS: frozenset[str] = frozenset(
    [
        "/api/chat/sessions",    # POST — create new chat session
        "/api/agents/spawn",     # POST — spawn a new agent
        "/ws/agent",             # WebSocket — open new agent connection
        "/api/sessions",         # POST — generic session creation endpoint
    ]
)


# ---------------------------------------------------------------------------
# In-memory fallback store (no Redis required for tests or single-node CE)
# ---------------------------------------------------------------------------

class _InMemoryThrottleStore:
    """
    Simple in-memory async-compatible store with per-key TTL semantics.

    Only tracks the *latest timestamp* per key; expiry is enforced lazily on
    ``get()``.  Thread-safe within a single async event loop via built-in
    Python dict operations (no concurrent writes from separate threads).
    """

    def __init__(self) -> None:
        # key → (value, expires_at_monotonic)
        self._store: dict[str, tuple[str, float]] = {}

    async def get(self, key: str) -> Optional[bytes]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value.encode()

    async def set(self, key: str, value: str, ex: int = 0) -> None:
        expires_at = time.monotonic() + max(ex, 1)
        self._store[key] = (value, expires_at)

    def clear(self) -> None:
        """Test-only helper — reset store between test cases."""
        self._store.clear()


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class TabThrottleMiddleware(BaseHTTPMiddleware):
    """
    Community Edition: enforce minimum delay between session-creation requests.
    Enterprise Edition: bypass completely (delay = 0 s).

    Returns HTTP 429 with a ``Retry-After`` header when the client is still
    within the cooldown window.  The frontend should read the header and
    silently retry — the user sees only a short spinner, not an error message.

    Parameters
    ----------
    app:
        The ASGI application to wrap.
    store:
        Async Redis-compatible store (``get`` / ``set``).  Defaults to the
        built-in ``_InMemoryThrottleStore``.
    delay_seconds:
        Minimum gap between session-creation requests (CE default: 1.0 s).
        Overridable via ``IRONCORE_TAB_THROTTLE_DELAY`` env var.
    key_prefix:
        Redis key namespace.
    """

    def __init__(
        self,
        app: Any,
        *,
        store: Any | None = None,
        delay_seconds: float = 1.0,
        key_prefix: str = "throttle:tab",
    ) -> None:
        super().__init__(app)
        self._store: Any = store if store is not None else _InMemoryThrottleStore()
        self._delay = delay_seconds
        self._prefix = key_prefix

    # ------------------------------------------------------------------
    # Starlette hook
    # ------------------------------------------------------------------

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # 1. Only throttle session-creation endpoints.
        if request.url.path not in THROTTLED_PATHS:
            return await call_next(request)

        # 2. Enterprise Edition bypasses throttle entirely.
        if is_enterprise():
            return await call_next(request)

        # 3. Allow if delay is disabled.
        if self._delay <= 0:
            return await call_next(request)

        # 4. Identify client.
        client_id = self._get_client_id(request)
        redis_key = f"{self._prefix}:{client_id}"

        # 5. Check cooldown.
        last_ts_raw = await self._store.get(redis_key)
        if last_ts_raw is not None:
            if isinstance(last_ts_raw, (bytes, bytearray)):
                last_ts = float(last_ts_raw.decode())
            else:
                last_ts = float(last_ts_raw)
            elapsed = time.time() - last_ts
            remaining = self._delay - elapsed
            if remaining > 0:
                retry_after = round(remaining, 3)
                logger.debug(
                    "[TabThrottle] client=%s path=%s retry_after=%.3fs",
                    client_id,
                    request.url.path,
                    retry_after,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limited",
                        "message": "Opening sessions too quickly. Please wait.",
                        "retry_after": retry_after,
                    },
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": "1",
                        "X-RateLimit-Reset": str(int(time.time() + remaining)),
                    },
                )

        # 6. Allow — record timestamp for next check.
        await self._store.set(redis_key, str(time.time()), ex=int(self._delay) + 1)
        return await call_next(request)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_client_id(self, request: Request) -> str:
        """
        Return the most-specific client identifier available.

        Priority:
          1. Authenticated ``user_id`` on ``request.state`` (set by auth middleware).
          2. First IP from ``X-Forwarded-For`` header (reverse proxy).
          3. Direct client host.

        Using ``user_id`` prevents bypassing the throttle by rotating source IPs.
        """
        user = getattr(request.state, "user", None)
        if user is not None:
            uid = getattr(user, "id", None) or getattr(user, "user_id", None)
            if uid:
                return f"user:{uid}"

        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            first_ip = forwarded.split(",")[0].strip()
            return f"ip:{first_ip}"

        if request.client:
            return f"ip:{request.client.host}"

        return "ip:unknown"
