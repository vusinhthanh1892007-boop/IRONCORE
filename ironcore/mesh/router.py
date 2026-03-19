"""Smart request routing for IronCore multi-node mesh.

Supports four strategies:
- SESSION_AFFINITY  — consistent hash on session_id (same session → same node)
- LEAST_LOADED      — route to the node with lowest current_load
- CAPABILITY_MATCH  — route to a node that has the required capabilities
- ROUND_ROBIN       — simple cycle through healthy nodes
"""

from __future__ import annotations

import hashlib
import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from ironcore.mesh.discovery import MeshDiscovery, NodeCapabilities, NodeInfo

logger = logging.getLogger(__name__)


class RoutingStrategy(str, Enum):
    SESSION_AFFINITY = "session_affinity"
    LEAST_LOADED = "least_loaded"
    CAPABILITY_MATCH = "capability_match"
    ROUND_ROBIN = "round_robin"


class MeshError(Exception):
    """Raised when a mesh operation cannot be completed."""


class MeshRouter:
    """Route incoming requests to the best available mesh node.

    Usage::

        router = MeshRouter(discovery)
        node = await router.route("chat", session_id="user-123")
        if node:
            result = await router.forward_request(node, "/api/chat", body, jwt_token)
    """

    def __init__(self, discovery: MeshDiscovery) -> None:
        self._discovery = discovery
        self._rr_index: int = 0

    # ------------------------------------------------------------------ public

    async def route(
        self,
        request_type: str,
        session_id: Optional[str] = None,
        required_capabilities: Optional[NodeCapabilities] = None,
        strategy: RoutingStrategy = RoutingStrategy.SESSION_AFFINITY,
    ) -> Optional[NodeInfo]:
        """Select the best node for a request.

        Returns *None* if no healthy node is available.
        """
        nodes = await self._discovery.get_healthy_nodes()
        if not nodes:
            return None

        if strategy == RoutingStrategy.SESSION_AFFINITY:
            if session_id:
                return self._consistent_hash(session_id, nodes)
            # Fallback: least loaded when no session_id is given
            return min(nodes, key=lambda n: n.capabilities.current_load)

        if strategy == RoutingStrategy.LEAST_LOADED:
            return min(nodes, key=lambda n: n.capabilities.current_load)

        if strategy == RoutingStrategy.CAPABILITY_MATCH:
            if required_capabilities:
                return self._match_capability(nodes, required_capabilities)
            return min(nodes, key=lambda n: n.capabilities.current_load)

        if strategy == RoutingStrategy.ROUND_ROBIN:
            return self._round_robin(nodes)

        # Unknown strategy — default to least loaded
        return min(nodes, key=lambda n: n.capabilities.current_load)

    async def forward_request(
        self,
        node: NodeInfo,
        path: str,
        body: Dict[str, Any],
        agent_jwt: str = "",
    ) -> Dict[str, Any]:
        """Forward an HTTP POST to another node, retrying once on failure.

        Injects the agent JWT as a Bearer token when provided.
        Raises :exc:`MeshError` if both attempts fail.
        """
        try:
            import httpx
        except ImportError as exc:
            raise MeshError("httpx not installed — cannot forward requests") from exc

        url = node.address.rstrip("/") + "/" + path.lstrip("/")
        headers: Dict[str, str] = {}
        if agent_jwt:
            headers["Authorization"] = f"Bearer {agent_jwt}"

        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json=body, headers=headers)
                    resp.raise_for_status()
                    return resp.json()  # type: ignore[no-any-return]
            except Exception as exc:
                if attempt == 1:
                    raise MeshError(
                        f"Forward request to {url} failed after retry: {exc}"
                    ) from exc
                logger.warning("[MeshRouter] Attempt 1 failed (%s), retrying…", exc)

        raise MeshError(f"Forward request to {url} failed")  # pragma: no cover

    # ----------------------------------------------------------------- private

    def _consistent_hash(self, session_id: str, nodes: List[NodeInfo]) -> NodeInfo:
        """Map *session_id* to a node deterministically via MD5 modulo."""
        index = int(hashlib.md5(session_id.encode(), usedforsecurity=False).hexdigest(), 16)
        return nodes[index % len(nodes)]

    def _round_robin(self, nodes: List[NodeInfo]) -> NodeInfo:
        node = nodes[self._rr_index % len(nodes)]
        self._rr_index += 1
        return node

    def _match_capability(
        self, nodes: List[NodeInfo], required: NodeCapabilities
    ) -> Optional[NodeInfo]:
        """Return the least-loaded node that satisfies *required* capabilities."""
        candidates: List[NodeInfo] = []
        for node in nodes:
            caps = node.capabilities
            if required.browser and not caps.browser:
                continue
            if required.gpu and not caps.gpu:
                continue
            if required.llm_models:
                if not any(m in caps.llm_models for m in required.llm_models):
                    continue
            candidates.append(node)
        if not candidates:
            return None
        return min(candidates, key=lambda n: n.capabilities.current_load)
