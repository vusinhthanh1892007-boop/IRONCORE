"""Phase 6 — Multi-node Mesh + Agent-to-Agent Auth — Test Suite.

All tests are self-contained: no real Redis, no network calls.
A _MockRedis class provides an in-memory implementation of the
redis.asyncio interface.
"""

from __future__ import annotations

import asyncio
import socket
import time
from typing import Any, Dict, List, Optional

import pytest

from ironcore.mesh.auth import AgentJWT, MeshAuthError
from ironcore.mesh.discovery import MeshDiscovery, NodeCapabilities, NodeInfo
from ironcore.mesh.router import MeshError, MeshRouter, RoutingStrategy


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

class _MockRedis:
    """In-memory Redis mock — covers setex / get / keys / delete."""

    def __init__(self) -> None:
        self._store: Dict[str, str] = {}
        self._expiry: Dict[str, float] = {}

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [k for k, exp in list(self._expiry.items()) if now > exp]
        for k in expired:
            self._store.pop(k, None)
            self._expiry.pop(k, None)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value
        self._expiry[key] = time.time() + ttl

    async def get(self, key: str) -> Optional[str]:
        self._purge_expired()
        return self._store.get(key)

    async def keys(self, pattern: str) -> List[str]:
        self._purge_expired()
        prefix = pattern.rstrip("*")
        return [k for k in self._store if k.startswith(prefix)]

    async def delete(self, key: str) -> int:
        if key in self._store:
            del self._store[key]
            self._expiry.pop(key, None)
            return 1
        return 0


def _make_node(
    node_id: str = "node-a",
    address: str = "http://localhost:8000",
    load: float = 0.0,
    browser: bool = False,
    gpu: bool = False,
    llm_models: Optional[List[str]] = None,
) -> NodeInfo:
    caps = NodeCapabilities(
        current_load=load,
        browser=browser,
        gpu=gpu,
        llm_models=llm_models or [],
    )
    return NodeInfo(node_id=node_id, address=address, capabilities=caps)


def _discovery_with_nodes(nodes: List[NodeInfo]) -> MeshDiscovery:
    """Stub MeshDiscovery whose get_healthy_nodes always returns *nodes*."""
    disc = MeshDiscovery(redis_client=None, this_node=_make_node("stub"))

    async def _stub() -> List[NodeInfo]:
        return nodes

    disc.get_healthy_nodes = _stub  # type: ignore[method-assign]
    return disc


# ══════════════════════════════════════════════════════════════════════════════
#  TestNodeCapabilities
# ══════════════════════════════════════════════════════════════════════════════

class TestNodeCapabilities:
    def test_defaults(self) -> None:
        caps = NodeCapabilities()
        assert caps.browser is False
        assert caps.gpu is False
        assert caps.llm_models == []
        assert caps.max_concurrent == 10
        assert caps.current_load == 0.0

    def test_custom_values(self) -> None:
        caps = NodeCapabilities(
            browser=True, gpu=True, llm_models=["llama3"], max_concurrent=20, current_load=0.5
        )
        assert caps.browser is True
        assert caps.llm_models == ["llama3"]
        assert caps.max_concurrent == 20

    def test_serialization_roundtrip(self) -> None:
        caps = NodeCapabilities(browser=True, gpu=False, llm_models=["qwen"])
        d = caps.model_dump()
        restored = NodeCapabilities(**d)
        assert restored.browser is True
        assert restored.llm_models == ["qwen"]


# ══════════════════════════════════════════════════════════════════════════════
#  TestNodeInfo
# ══════════════════════════════════════════════════════════════════════════════

class TestNodeInfo:
    def test_default_node_id_contains_hostname(self) -> None:
        node = NodeInfo(address="http://localhost:8000")
        assert socket.gethostname() in node.node_id

    def test_custom_node_id(self) -> None:
        node = _make_node("my-node", "http://192.168.1.1:9000")
        assert node.node_id == "my-node"
        assert node.address == "http://192.168.1.1:9000"

    def test_status_defaults_healthy(self) -> None:
        node = NodeInfo(address="http://localhost:8000")
        assert node.status == "healthy"

    def test_last_seen_defaults_to_now(self) -> None:
        before = time.time()
        node = NodeInfo(address="http://localhost:8000")
        after = time.time()
        assert before <= node.last_seen <= after

    def test_serialization_roundtrip(self) -> None:
        node = _make_node("serial-node")
        restored = NodeInfo.model_validate_json(node.model_dump_json())
        assert restored.node_id == "serial-node"
        assert restored.address == node.address


# ══════════════════════════════════════════════════════════════════════════════
#  TestMeshDiscovery
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestMeshDiscovery:
    async def test_start_sets_running(self) -> None:
        redis = _MockRedis()
        disc = MeshDiscovery(redis_client=redis, this_node=_make_node("run-node"))
        await disc.start()
        assert disc._running is True
        await disc.stop()

    async def test_stop_clears_running(self) -> None:
        redis = _MockRedis()
        disc = MeshDiscovery(redis_client=redis, this_node=_make_node("stop-node"))
        await disc.start()
        await disc.stop()
        assert disc._running is False

    async def test_publish_heartbeat_stores_in_redis(self) -> None:
        redis = _MockRedis()
        disc = MeshDiscovery(redis_client=redis, this_node=_make_node("hb-node"))
        await disc._publish_heartbeat()
        keys = await redis.keys("ironcore:nodes:*")
        assert any("hb-node" in k for k in keys)

    async def test_get_all_nodes_returns_published_node(self) -> None:
        redis = _MockRedis()
        disc = MeshDiscovery(redis_client=redis, this_node=_make_node("visible-node"))
        await disc._publish_heartbeat()
        nodes = await disc.get_all_nodes()
        assert any(n.node_id == "visible-node" for n in nodes)

    async def test_get_healthy_nodes_includes_fresh(self) -> None:
        redis = _MockRedis()
        disc = MeshDiscovery(redis_client=redis, this_node=_make_node("fresh-node"))
        await disc._publish_heartbeat()
        healthy = await disc.get_healthy_nodes()
        assert any(n.node_id == "fresh-node" for n in healthy)

    async def test_get_healthy_nodes_excludes_stale(self) -> None:
        redis = _MockRedis()
        disc = MeshDiscovery(redis_client=redis, this_node=_make_node("main"))
        # Manually inject a stale node (last_seen far in the past)
        stale = NodeInfo(node_id="stale-node", address="http://stale:8000", last_seen=1.0)
        redis._store["ironcore:nodes:stale-node"] = stale.model_dump_json()
        redis._expiry["ironcore:nodes:stale-node"] = time.time() + 1000  # Redis TTL ok
        healthy = await disc.get_healthy_nodes()
        assert not any(n.node_id == "stale-node" for n in healthy)

    async def test_stop_deregisters_from_redis(self) -> None:
        redis = _MockRedis()
        disc = MeshDiscovery(redis_client=redis, this_node=_make_node("dereg-node"))
        await disc.start()
        keys_before = await redis.keys("ironcore:nodes:*")
        assert any("dereg-node" in k for k in keys_before)
        await disc.stop()
        keys_after = await redis.keys("ironcore:nodes:*")
        assert not any("dereg-node" in k for k in keys_after)

    async def test_multiple_nodes_discoverable(self) -> None:
        redis = _MockRedis()
        for nid in ("multi-a", "multi-b", "multi-c"):
            disc = MeshDiscovery(redis_client=redis, this_node=_make_node(nid))
            await disc._publish_heartbeat()
        disc_a = MeshDiscovery(redis_client=redis, this_node=_make_node("multi-a"))
        nodes = await disc_a.get_all_nodes()
        ids = {n.node_id for n in nodes}
        assert {"multi-a", "multi-b", "multi-c"}.issubset(ids)

    async def test_no_redis_fallback_to_in_memory(self) -> None:
        disc = MeshDiscovery(redis_client=None, this_node=_make_node("local-node"))
        await disc._publish_heartbeat()
        nodes = await disc.get_all_nodes()
        assert any(n.node_id == "local-node" for n in nodes)

    async def test_no_redis_get_healthy_includes_fresh(self) -> None:
        disc = MeshDiscovery(redis_client=None, this_node=_make_node("local-healthy"))
        await disc._publish_heartbeat()
        healthy = await disc.get_healthy_nodes()
        assert any(n.node_id == "local-healthy" for n in healthy)

    async def test_publish_updates_last_seen_timestamp(self) -> None:
        redis = _MockRedis()
        disc = MeshDiscovery(redis_client=redis, this_node=_make_node("ts-node"))
        before = time.time()
        await disc._publish_heartbeat()
        after = time.time()
        assert before <= disc._this_node.last_seen <= after

    async def test_no_redis_stop_removes_from_memory(self) -> None:
        disc = MeshDiscovery(redis_client=None, this_node=_make_node("mem-node"))
        await disc._publish_heartbeat()
        assert "mem-node" in disc._nodes
        await disc.stop()
        assert "mem-node" not in disc._nodes


# ══════════════════════════════════════════════════════════════════════════════
#  TestMeshRouter
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestMeshRouter:
    async def test_no_nodes_returns_none(self) -> None:
        router = MeshRouter(_discovery_with_nodes([]))
        assert await router.route("chat", session_id="s1") is None

    async def test_session_affinity_consistent(self) -> None:
        nodes = [_make_node(f"node-{i}") for i in range(5)]
        router = MeshRouter(_discovery_with_nodes(nodes))
        r1 = await router.route("chat", session_id="user-abc", strategy=RoutingStrategy.SESSION_AFFINITY)
        r2 = await router.route("chat", session_id="user-abc", strategy=RoutingStrategy.SESSION_AFFINITY)
        assert r1 is not None and r2 is not None
        assert r1.node_id == r2.node_id

    async def test_session_affinity_different_sessions_spread(self) -> None:
        nodes = [_make_node(f"spread-{i}") for i in range(10)]
        router = MeshRouter(_discovery_with_nodes(nodes))
        destinations = {
            (await router.route("chat", session_id=f"session-{i}", strategy=RoutingStrategy.SESSION_AFFINITY)).node_id  # type: ignore[union-attr]
            for i in range(30)
        }
        assert len(destinations) > 1

    async def test_session_affinity_no_session_uses_least_loaded(self) -> None:
        nodes = [_make_node("heavy", load=0.9), _make_node("light", load=0.1)]
        router = MeshRouter(_discovery_with_nodes(nodes))
        result = await router.route("chat", strategy=RoutingStrategy.SESSION_AFFINITY)
        assert result is not None
        assert result.node_id == "light"

    async def test_least_loaded_picks_minimum(self) -> None:
        nodes = [_make_node("a", load=0.7), _make_node("b", load=0.2), _make_node("c", load=0.9)]
        router = MeshRouter(_discovery_with_nodes(nodes))
        result = await router.route("chat", strategy=RoutingStrategy.LEAST_LOADED)
        assert result is not None
        assert result.node_id == "b"

    async def test_round_robin_cycles_through_all(self) -> None:
        nodes = [_make_node(f"rr-{i}") for i in range(3)]
        router = MeshRouter(_discovery_with_nodes(nodes))
        results = [
            (await router.route("chat", strategy=RoutingStrategy.ROUND_ROBIN)).node_id  # type: ignore[union-attr]
            for _ in range(6)
        ]
        assert set(results) == {"rr-0", "rr-1", "rr-2"}

    async def test_capability_match_browser(self) -> None:
        nodes = [_make_node("no-browser", browser=False), _make_node("has-browser", browser=True)]
        router = MeshRouter(_discovery_with_nodes(nodes))
        result = await router.route(
            "browse",
            required_capabilities=NodeCapabilities(browser=True),
            strategy=RoutingStrategy.CAPABILITY_MATCH,
        )
        assert result is not None
        assert result.node_id == "has-browser"

    async def test_capability_match_gpu(self) -> None:
        nodes = [_make_node("cpu", gpu=False), _make_node("gpu", gpu=True)]
        router = MeshRouter(_discovery_with_nodes(nodes))
        result = await router.route(
            "llm",
            required_capabilities=NodeCapabilities(gpu=True),
            strategy=RoutingStrategy.CAPABILITY_MATCH,
        )
        assert result is not None
        assert result.node_id == "gpu"

    async def test_capability_match_llm_model(self) -> None:
        nodes = [
            _make_node("llama-node", llm_models=["llama3"]),
            _make_node("qwen-node", llm_models=["qwen-72b"]),
        ]
        router = MeshRouter(_discovery_with_nodes(nodes))
        result = await router.route(
            "llm",
            required_capabilities=NodeCapabilities(llm_models=["qwen-72b"]),
            strategy=RoutingStrategy.CAPABILITY_MATCH,
        )
        assert result is not None
        assert result.node_id == "qwen-node"

    async def test_capability_no_match_returns_none(self) -> None:
        nodes = [_make_node("cpu-only", gpu=False)]
        router = MeshRouter(_discovery_with_nodes(nodes))
        result = await router.route(
            "llm",
            required_capabilities=NodeCapabilities(gpu=True),
            strategy=RoutingStrategy.CAPABILITY_MATCH,
        )
        assert result is None

    async def test_consistent_hash_is_deterministic(self) -> None:
        nodes = [_make_node(f"ch-{i}") for i in range(5)]
        router = MeshRouter(_discovery_with_nodes(nodes))
        first = router._consistent_hash("stable-session", nodes).node_id
        for _ in range(10):
            assert router._consistent_hash("stable-session", nodes).node_id == first

    async def test_default_no_session_least_loaded(self) -> None:
        nodes = [_make_node("busy", load=0.95), _make_node("idle", load=0.05)]
        router = MeshRouter(_discovery_with_nodes(nodes))
        result = await router.route("batch")
        assert result is not None
        assert result.node_id == "idle"

    async def test_capability_match_no_required_falls_back(self) -> None:
        """CAPABILITY_MATCH with no requirements should still return least-loaded."""
        nodes = [_make_node("x", load=0.8), _make_node("y", load=0.2)]
        router = MeshRouter(_discovery_with_nodes(nodes))
        result = await router.route("chat", strategy=RoutingStrategy.CAPABILITY_MATCH)
        assert result is not None
        assert result.node_id == "y"


# ══════════════════════════════════════════════════════════════════════════════
#  TestAgentJWT
# ══════════════════════════════════════════════════════════════════════════════

class TestAgentJWT:
    def test_empty_secret_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            AgentJWT("")

    def test_issue_produces_three_dot_parts(self) -> None:
        token = AgentJWT("secret").issue(_make_node("n"))
        assert token.count(".") == 2

    def test_verify_valid_token_returns_payload(self) -> None:
        jwt = AgentJWT("shared-secret")
        node = _make_node("node-valid")
        payload = jwt.verify(jwt.issue(node))
        assert payload["sub"] == "node-valid"
        assert payload["iss"] == "ironcore-mesh"

    def test_verify_wrong_secret_raises(self) -> None:
        token = AgentJWT("secret-a").issue(_make_node("n"))
        with pytest.raises(MeshAuthError, match="[Ss]ignature"):
            AgentJWT("secret-b").verify(token)

    def test_verify_expired_token_raises(self, monkeypatch: Any) -> None:
        import ironcore.mesh.auth as auth_module

        jwt = AgentJWT("secret")
        node = _make_node("node-exp")
        monkeypatch.setattr(auth_module, "_TOKEN_EXPIRY_SECONDS", -1)
        expired_token = jwt.issue(node)
        with pytest.raises(MeshAuthError, match="[Ee]xpir"):
            jwt.verify(expired_token)

    def test_verify_wrong_issuer_raises(self, monkeypatch: Any) -> None:
        import ironcore.mesh.auth as auth_module

        jwt = AgentJWT("secret")
        node = _make_node("node-iss")
        monkeypatch.setattr(auth_module, "_ISSUER", "evil-mesh")
        evil_token = jwt.issue(node)
        monkeypatch.setattr(auth_module, "_ISSUER", "ironcore-mesh")
        with pytest.raises(MeshAuthError, match="[Ii]ssuer"):
            jwt.verify(evil_token)

    def test_verify_invalid_format_raises(self) -> None:
        with pytest.raises(MeshAuthError):
            AgentJWT("secret").verify("only.two")

    def test_verify_too_many_parts_raises(self) -> None:
        with pytest.raises(MeshAuthError):
            AgentJWT("secret").verify("a.b.c.d")

    def test_payload_contains_capabilities(self) -> None:
        node = NodeInfo(
            node_id="cap-node",
            address="http://cap:8000",
            capabilities=NodeCapabilities(browser=True, gpu=True, llm_models=["llama3"]),
        )
        jwt = AgentJWT("secret")
        payload = jwt.verify(jwt.issue(node))
        assert payload["capabilities"]["browser"] is True
        assert payload["capabilities"]["gpu"] is True
        assert "llama3" in payload["capabilities"]["llm_models"]

    def test_two_instances_same_secret_interoperate(self) -> None:
        issuer = AgentJWT("shared")
        verifier = AgentJWT("shared")
        token = issuer.issue(_make_node("interop"))
        payload = verifier.verify(token)
        assert payload["sub"] == "interop"

    def test_token_sub_matches_node_id(self) -> None:
        node = _make_node("custom-id-42")
        jwt = AgentJWT("s3cr3t")
        payload = jwt.verify(jwt.issue(node))
        assert payload["sub"] == "custom-id-42"

    def test_token_exp_in_future(self) -> None:
        jwt = AgentJWT("secret")
        payload = jwt.verify(jwt.issue(_make_node("n")))
        assert payload["exp"] > int(time.time())


# ══════════════════════════════════════════════════════════════════════════════
#  TestMeshIntegration
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestMeshIntegration:
    async def test_discover_then_route_least_loaded(self) -> None:
        redis = _MockRedis()
        light = _make_node("light-int", load=0.1)
        heavy = _make_node("heavy-int", load=0.9)
        for node in (light, heavy):
            disc = MeshDiscovery(redis_client=redis, this_node=node)
            await disc._publish_heartbeat()
        router = MeshRouter(MeshDiscovery(redis_client=redis, this_node=_make_node("router")))
        result = await router.route("chat", strategy=RoutingStrategy.LEAST_LOADED)
        assert result is not None
        assert result.node_id == "light-int"

    async def test_jwt_roundtrip_with_capabilities(self) -> None:
        node = NodeInfo(
            node_id="full-node",
            address="http://full:8000",
            capabilities=NodeCapabilities(browser=True, llm_models=["qwen-72b"]),
        )
        jwt = AgentJWT("integration-secret")
        payload = jwt.verify(jwt.issue(node))
        assert payload["sub"] == "full-node"
        assert payload["capabilities"]["llm_models"] == ["qwen-72b"]

    async def test_session_affinity_stable_across_calls(self) -> None:
        nodes = [_make_node(f"stable-{i}") for i in range(5)]
        router = MeshRouter(_discovery_with_nodes(nodes))
        session = "persistent-user-session-xyz"
        first = await router.route("chat", session_id=session)
        for _ in range(5):
            result = await router.route("chat", session_id=session)
            assert result is not None
            assert result.node_id == first.node_id  # type: ignore[union-attr]

    async def test_full_mesh_lifecycle(self) -> None:
        """Start discovery → publish → route → stop → deregistered."""
        redis = _MockRedis()
        node = _make_node("lifecycle-node")
        disc = MeshDiscovery(redis_client=redis, this_node=node)
        await disc.start()
        healthy = await disc.get_healthy_nodes()
        assert any(n.node_id == "lifecycle-node" for n in healthy)
        await disc.stop()
        keys = await redis.keys("ironcore:nodes:*")
        assert not any("lifecycle-node" in k for k in keys)
