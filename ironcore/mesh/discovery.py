"""Node discovery & registry for IronCore multi-node mesh.

Each node publishes a heartbeat to Redis every HEARTBEAT_INTERVAL seconds.
If no Redis is available the registry falls back to an in-memory dict so
single-node deployments need no extra infrastructure.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import socket
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class NodeCapabilities(BaseModel):
    """Hardware / software capabilities advertised by a mesh node."""

    browser: bool = False
    gpu: bool = False
    llm_models: List[str] = []
    max_concurrent: int = 10
    current_load: float = 0.0  # 0.0–1.0


class NodeInfo(BaseModel):
    """Identity and capabilities of a single mesh node."""

    node_id: str = Field(
        default_factory=lambda: socket.gethostname() + "-" + secrets.token_hex(4)
    )
    address: str = "http://localhost:8000"
    capabilities: NodeCapabilities = Field(default_factory=NodeCapabilities)
    status: str = "healthy"
    last_seen: float = Field(default_factory=time.time)
    registered_at: float = Field(default_factory=time.time)


class MeshDiscovery:
    """Publish heartbeats and discover peer nodes via Redis (or in-memory).

    Usage::

        redis = aioredis.from_url("redis://localhost")
        this_node = NodeInfo(address="http://my-host:8000")
        disc = MeshDiscovery(redis_client=redis, this_node=this_node)
        await disc.start()          # begins heartbeat loop
        nodes = await disc.get_healthy_nodes()
        await disc.stop()
    """

    HEARTBEAT_INTERVAL: int = 10  # seconds — can be overridden per-instance for tests
    NODE_TTL: int = 30            # seconds — nodes not seen for this long are stale
    KEY_PREFIX: str = "ironcore:nodes:"

    def __init__(self, redis_client: Any, this_node: NodeInfo) -> None:
        self._redis = redis_client
        self._this_node = this_node
        # In-memory fallback when no Redis is available
        self._nodes: Dict[str, NodeInfo] = {}
        self._heartbeat_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._running = False

    # ------------------------------------------------------------------ public

    async def start(self) -> None:
        """Start heartbeat loop and publish this node immediately."""
        self._running = True
        await self._publish_heartbeat()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("[MeshDiscovery] Started | node_id=%s", self._this_node.node_id)

    async def stop(self) -> None:
        """Stop heartbeat and deregister this node."""
        self._running = False
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        # Deregister
        if self._redis is not None:
            try:
                await self._redis.delete(self.KEY_PREFIX + self._this_node.node_id)
            except Exception as exc:  # pragma: no cover
                logger.warning("[MeshDiscovery] Deregister error: %s", exc)
        else:
            self._nodes.pop(self._this_node.node_id, None)
        logger.info("[MeshDiscovery] Stopped | node_id=%s", self._this_node.node_id)

    async def get_all_nodes(self) -> List[NodeInfo]:
        """Return all nodes currently registered in Redis (or in-memory)."""
        if self._redis is None:
            return list(self._nodes.values())
        nodes: List[NodeInfo] = []
        try:
            keys = await self._redis.keys(self.KEY_PREFIX + "*")
            for key in keys:
                data = await self._redis.get(key)
                if data:
                    nodes.append(NodeInfo.model_validate_json(data))
        except Exception as exc:
            logger.warning("[MeshDiscovery] get_all_nodes error: %s", exc)
        return nodes

    async def get_healthy_nodes(self) -> List[NodeInfo]:
        """Return nodes whose last_seen is within NODE_TTL seconds."""
        now = time.time()
        return [n for n in await self.get_all_nodes() if now - n.last_seen <= self.NODE_TTL]

    # ----------------------------------------------------------------- private

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                await asyncio.wait_for(
                    asyncio.shield(asyncio.sleep(self.HEARTBEAT_INTERVAL)),
                    timeout=self.HEARTBEAT_INTERVAL + 1,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                if not self._running:
                    break
            if not self._running:
                break
            try:
                await self._publish_heartbeat()
            except Exception as exc:
                logger.warning("[MeshDiscovery] Heartbeat publish error: %s", exc)

    async def _publish_heartbeat(self) -> None:
        self._this_node.last_seen = time.time()
        if self._redis is not None:
            key = self.KEY_PREFIX + self._this_node.node_id
            data = self._this_node.model_dump_json()
            await self._redis.setex(key, self.NODE_TTL, data)
        else:
            self._nodes[self._this_node.node_id] = self._this_node
