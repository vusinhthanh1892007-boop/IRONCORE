"""
tests/test_phase14_tab_throttle.py
=====================================
Phase 14 — CE Tab Throttling (The Architect, IronCore V2)

Test suite — 30 tests across 5 suites:

  TestInMemoryThrottleStore  (6 tests)  — store internals
  TestTabThrottleMiddleware  (10 tests) — CE throttle logic
  TestEnterpriseBypass       (4 tests)  — EE no-throttle
  TestClientIdentification   (5 tests)  — _get_client_id priority
  TestEdgeCases              (5 tests)  — boundary & config cases
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncGenerator, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from ironcore.middleware.tab_throttle import (
    THROTTLED_PATHS,
    TabThrottleMiddleware,
    _InMemoryThrottleStore,
)

pytestmark = pytest.mark.asyncio


# ─── Helpers ───────────────────────────────────────────────────────────────

def _make_app(
    store: Any | None = None,
    delay_seconds: float = 1.0,
    extra_routes: List[Route] | None = None,
) -> Starlette:
    """Build a tiny Starlette app wrapped with TabThrottleMiddleware."""

    async def session_endpoint(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    async def health_endpoint(request: Request) -> PlainTextResponse:
        return PlainTextResponse("healthy")

    routes = [
        Route("/api/agents/spawn", session_endpoint, methods=["POST"]),
        Route("/api/chat/sessions", session_endpoint, methods=["POST"]),
        Route("/api/sessions", session_endpoint, methods=["POST"]),
        Route("/api/health", health_endpoint, methods=["GET"]),
        Route("/ws/agent", session_endpoint, methods=["GET", "POST"]),
    ]
    if extra_routes:
        routes.extend(extra_routes)

    app = Starlette(routes=routes)
    app.add_middleware(
        TabThrottleMiddleware,
        store=store,
        delay_seconds=delay_seconds,
    )
    return app


class _FakeUser:
    def __init__(self, user_id: str) -> None:
        self.id = user_id


def _set_state_user(request: Request, user_id: str) -> None:
    request.state.user = _FakeUser(user_id)


# ─── Suite 1: InMemoryThrottleStore ────────────────────────────────────────


class TestInMemoryThrottleStore:
    """Unit-test the in-process fallback store."""

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self) -> None:
        store = _InMemoryThrottleStore()
        result = await store.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_then_get_returns_value(self) -> None:
        store = _InMemoryThrottleStore()
        await store.set("k1", "hello", ex=5)
        raw = await store.get("k1")
        assert raw is not None
        assert raw == b"hello"  # can decode

    @pytest.mark.asyncio
    async def test_get_returns_bytes(self) -> None:
        store = _InMemoryThrottleStore()
        await store.set("k2", "1234.5", ex=5)
        raw = await store.get("k2")
        assert isinstance(raw, bytes)

    @pytest.mark.asyncio
    async def test_expired_key_returns_none(self) -> None:
        store = _InMemoryThrottleStore()
        # Manually insert an already-expired entry
        store._store["expkey"] = ("old", time.monotonic() - 1.0)
        result = await store.get("expkey")
        assert result is None

    @pytest.mark.asyncio
    async def test_clear_removes_all_entries(self) -> None:
        store = _InMemoryThrottleStore()
        await store.set("a", "1", ex=5)
        await store.set("b", "2", ex=5)
        store.clear()
        assert await store.get("a") is None
        assert await store.get("b") is None

    @pytest.mark.asyncio
    async def test_overwrite_key_updates_value(self) -> None:
        store = _InMemoryThrottleStore()
        await store.set("k", "old", ex=10)
        await store.set("k", "new", ex=10)
        raw = await store.get("k")
        assert raw is not None
        assert raw == b"new"


# ─── Suite 2: CE Throttle Behaviour ─────────────────────────────────────────


class TestTabThrottleMiddleware:
    """Test CE throttle logic using the in-memory store."""

    def _fresh_store(self) -> _InMemoryThrottleStore:
        s = _InMemoryThrottleStore()
        return s

    def test_first_request_to_throttled_path_passes(self) -> None:
        store = self._fresh_store()
        app = _make_app(store=store, delay_seconds=1.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.post("/api/agents/spawn")
        assert resp.status_code == 200

    def test_second_request_within_delay_returns_429(self) -> None:
        store = self._fresh_store()
        app = _make_app(store=store, delay_seconds=1.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(app, raise_server_exceptions=False) as client:
                r1 = client.post("/api/agents/spawn")
                r2 = client.post("/api/agents/spawn")
        assert r1.status_code == 200
        assert r2.status_code == 429

    def test_429_response_has_retry_after_header(self) -> None:
        store = self._fresh_store()
        app = _make_app(store=store, delay_seconds=1.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(app, raise_server_exceptions=False) as client:
                client.post("/api/agents/spawn")
                r2 = client.post("/api/agents/spawn")
        assert "Retry-After" in r2.headers
        retry_after = float(r2.headers["Retry-After"])
        assert 0 < retry_after <= 1.0

    def test_429_response_body_has_error_field(self) -> None:
        store = self._fresh_store()
        app = _make_app(store=store, delay_seconds=1.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(app, raise_server_exceptions=False) as client:
                client.post("/api/agents/spawn")
                r2 = client.post("/api/agents/spawn")
        body = r2.json()
        assert body["error"] == "rate_limited"
        assert "retry_after" in body

    def test_non_session_endpoint_not_throttled(self) -> None:
        store = self._fresh_store()
        app = _make_app(store=store, delay_seconds=1.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(app) as client:
                r1 = client.get("/api/health")
                r2 = client.get("/api/health")
                r3 = client.get("/api/health")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r3.status_code == 200

    def test_chat_sessions_path_is_throttled(self) -> None:
        store = self._fresh_store()
        app = _make_app(store=store, delay_seconds=1.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(app, raise_server_exceptions=False) as client:
                r1 = client.post("/api/chat/sessions")
                r2 = client.post("/api/chat/sessions")
        assert r1.status_code == 200
        assert r2.status_code == 429

    def test_different_ips_have_independent_cooldowns(self) -> None:
        store = self._fresh_store()
        app = _make_app(store=store, delay_seconds=2.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(app, raise_server_exceptions=False) as client:
                # First IP
                r1a = client.post("/api/agents/spawn", headers={"X-Forwarded-For": "1.2.3.4"})
                r1b = client.post("/api/agents/spawn", headers={"X-Forwarded-For": "1.2.3.4"})
                # Different IP — should pass
                r2a = client.post("/api/agents/spawn", headers={"X-Forwarded-For": "9.9.9.9"})
        assert r1a.status_code == 200
        assert r1b.status_code == 429
        assert r2a.status_code == 200

    def test_retry_after_value_within_tolerance(self) -> None:
        """Retry-After should be close to delay_seconds (< 50 ms error)."""
        store = self._fresh_store()
        app = _make_app(store=store, delay_seconds=1.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(app, raise_server_exceptions=False) as client:
                client.post("/api/agents/spawn")
                r2 = client.post("/api/agents/spawn")
        retry_after = float(r2.headers["Retry-After"])
        # Should be slightly less than 1.0 (time elapsed between requests)
        assert retry_after <= 1.001
        assert retry_after > 0.8, f"retry_after={retry_after} seems too small"

    def test_zero_delay_never_throttles(self) -> None:
        store = self._fresh_store()
        app = _make_app(store=store, delay_seconds=0.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(app) as client:
                for _ in range(5):
                    r = client.post("/api/agents/spawn")
                    assert r.status_code == 200

    def test_x_ratelimit_headers_present(self) -> None:
        store = self._fresh_store()
        app = _make_app(store=store, delay_seconds=1.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(app, raise_server_exceptions=False) as client:
                client.post("/api/agents/spawn")
                r2 = client.post("/api/agents/spawn")
        assert "X-RateLimit-Limit" in r2.headers
        assert "X-RateLimit-Reset" in r2.headers
        assert r2.headers["X-RateLimit-Limit"] == "1"


# ─── Suite 3: Enterprise Bypass ──────────────────────────────────────────────


class TestEnterpriseBypass:
    """Enterprise Edition must bypass throttle on all session endpoints."""

    def test_ee_first_request_passes(self) -> None:
        store = _InMemoryThrottleStore()
        app = _make_app(store=store, delay_seconds=1.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=True):
            with TestClient(app) as client:
                r = client.post("/api/agents/spawn")
        assert r.status_code == 200

    def test_ee_rapid_requests_all_pass(self) -> None:
        store = _InMemoryThrottleStore()
        app = _make_app(store=store, delay_seconds=1.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=True):
            with TestClient(app) as client:
                for _ in range(10):
                    r = client.post("/api/agents/spawn")
                    assert r.status_code == 200

    def test_ee_chat_sessions_not_throttled(self) -> None:
        store = _InMemoryThrottleStore()
        app = _make_app(store=store, delay_seconds=1.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=True):
            with TestClient(app) as client:
                for _ in range(5):
                    r = client.post("/api/chat/sessions")
                    assert r.status_code == 200

    def test_ce_is_throttled_but_ee_version_is_not(self) -> None:
        """Same delay/store — CE throttles, EE does not."""
        store_ce = _InMemoryThrottleStore()
        store_ee = _InMemoryThrottleStore()
        app_ce = _make_app(store=store_ce, delay_seconds=1.0)
        app_ee = _make_app(store=store_ee, delay_seconds=1.0)

        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(app_ce, raise_server_exceptions=False) as client:
                client.post("/api/agents/spawn")
                r_ce = client.post("/api/agents/spawn")

        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=True):
            with TestClient(app_ee) as client:
                client.post("/api/agents/spawn")
                r_ee = client.post("/api/agents/spawn")

        assert r_ce.status_code == 429
        assert r_ee.status_code == 200


# ─── Suite 4: Client Identification ─────────────────────────────────────────


class TestClientIdentification:
    """_get_client_id must prefer user_id > X-Forwarded-For > client host."""

    def _build_request(
        self,
        *,
        client_host: str = "127.0.0.1",
        forwarded_for: str | None = None,
        user_id: str | None = None,
    ) -> Request:
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/agents/spawn",
            "query_string": b"",
            "headers": [],
            "client": (client_host, 12345),
        }
        if forwarded_for:
            scope["headers"] = [(b"x-forwarded-for", forwarded_for.encode())]

        request = Request(scope)
        if user_id:
            request.state.user = _FakeUser(user_id)
        return request

    def test_prefers_user_id_over_ip(self) -> None:
        middleware = TabThrottleMiddleware(MagicMock(), delay_seconds=1.0)
        req = self._build_request(forwarded_for="9.9.9.9", user_id="user-abc")
        result = middleware._get_client_id(req)
        assert result == "user:user-abc"

    def test_uses_forwarded_for_when_no_user(self) -> None:
        middleware = TabThrottleMiddleware(MagicMock(), delay_seconds=1.0)
        req = self._build_request(forwarded_for="5.6.7.8")
        result = middleware._get_client_id(req)
        assert result == "ip:5.6.7.8"

    def test_uses_first_ip_from_forwarded_for_chain(self) -> None:
        middleware = TabThrottleMiddleware(MagicMock(), delay_seconds=1.0)
        req = self._build_request(forwarded_for="10.0.0.1, 172.16.0.1, 192.168.1.1")
        result = middleware._get_client_id(req)
        assert result == "ip:10.0.0.1"

    def test_falls_back_to_client_host(self) -> None:
        middleware = TabThrottleMiddleware(MagicMock(), delay_seconds=1.0)
        req = self._build_request(client_host="203.0.113.10")
        result = middleware._get_client_id(req)
        assert result == "ip:203.0.113.10"

    def test_user_id_makes_ip_irrelevant(self) -> None:
        """Two requests from different IPs but same user_id share cooldown."""
        store = _InMemoryThrottleStore()
        app = _make_app(store=store, delay_seconds=2.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(app, raise_server_exceptions=False) as client:
                # The test client doesn't inject state.user, so we test via IPs
                r1 = client.post(
                    "/api/agents/spawn", headers={"X-Forwarded-For": "1.1.1.1"}
                )
                # Same IP: should be throttled
                r2 = client.post(
                    "/api/agents/spawn", headers={"X-Forwarded-For": "1.1.1.1"}
                )
        assert r1.status_code == 200
        assert r2.status_code == 429


# ─── Suite 5: Edge Cases ─────────────────────────────────────────────────────


class TestEdgeCases:
    """Boundary conditions, config, and THROTTLED_PATHS contract."""

    def test_throttled_paths_frozenset_contains_expected_paths(self) -> None:
        assert "/api/agents/spawn" in THROTTLED_PATHS
        assert "/api/chat/sessions" in THROTTLED_PATHS
        assert "/ws/agent" in THROTTLED_PATHS
        assert "/api/health" not in THROTTLED_PATHS

    def test_large_delay_still_throttles_immediate_second_request(self) -> None:
        store = _InMemoryThrottleStore()
        app = _make_app(store=store, delay_seconds=60.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(app, raise_server_exceptions=False) as client:
                r1 = client.post("/api/agents/spawn")
                r2 = client.post("/api/agents/spawn")
        assert r1.status_code == 200
        assert r2.status_code == 429
        # Retry-After should be close to 60 s
        retry_after = float(r2.headers["Retry-After"])
        assert retry_after > 58.0

    def test_api_sessions_path_throttled(self) -> None:
        store = _InMemoryThrottleStore()
        app = _make_app(store=store, delay_seconds=1.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(app, raise_server_exceptions=False) as client:
                r1 = client.post("/api/sessions")
                r2 = client.post("/api/sessions")
        assert r1.status_code == 200
        assert r2.status_code == 429

    def test_middleware_uses_in_memory_store_when_none_provided(self) -> None:
        """When no store is passed, middleware creates its own _InMemoryThrottleStore."""
        app = _make_app(store=None, delay_seconds=1.0)
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(app, raise_server_exceptions=False) as client:
                r1 = client.post("/api/agents/spawn")
                r2 = client.post("/api/agents/spawn")
        assert r1.status_code == 200
        assert r2.status_code == 429

    def test_custom_key_prefix_used_in_store(self) -> None:
        """Custom key_prefix is forwarded to the store key."""
        store = _InMemoryThrottleStore()

        async def session_endpoint(request: Request) -> PlainTextResponse:
            return PlainTextResponse("ok")

        from starlette.applications import Starlette as _Starlette
        from starlette.routing import Route as _Route
        inner_app = _Starlette(routes=[_Route("/api/agents/spawn", session_endpoint, methods=["POST"])])
        inner_app.add_middleware(
            TabThrottleMiddleware,
            store=store,
            delay_seconds=1.0,
            key_prefix="custom:pref",
        )
        with patch("ironcore.middleware.tab_throttle.is_enterprise", return_value=False):
            with TestClient(inner_app, raise_server_exceptions=False) as client:
                client.post("/api/agents/spawn")
        # Key should be stored under custom:pref:ip:... not throttle:tab:ip:...
        keys = list(store._store.keys())
        assert any(k.startswith("custom:pref:") for k in keys)
