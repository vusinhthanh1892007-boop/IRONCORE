"""Phase 16 — Live Cost Dashboard Broadcaster (SSE fan-out).

DashboardBroadcaster maintains a set of asyncio.Queue per active SSE connection
and fans out cost snapshots + alert events to all subscribers.

Integration:
    broadcaster = DashboardBroadcaster()
    guard.add_alert_callback(broadcaster.on_alert)

    # In FastAPI endpoint:
    async for chunk in broadcaster.subscribe():
        yield chunk
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from ironcore.enterprise.budget.guard import BudgetGuard
from ironcore.enterprise.budget.ledger import SpendSnapshot
from ironcore.enterprise.budget.policy import BudgetAlert, BudgetPolicy, BudgetWindow

logger = logging.getLogger(__name__)

# ── Configuration via env vars ──────────────────────────────────────────────
_ENABLED = os.environ.get("IRONCORE_BUDGET_DASHBOARD_ENABLED", "true").lower() != "false"
_PUSH_INTERVAL = float(os.environ.get("IRONCORE_BUDGET_DASHBOARD_PUSH_INTERVAL", "5.0"))
_MAX_CONNECTIONS = int(os.environ.get("IRONCORE_BUDGET_DASHBOARD_MAX_CONNECTIONS", "50"))


def _encode_sse(data: Dict[str, Any], event: str = "budget") -> str:
    """Format a dict as a Server-Sent Events message."""
    payload = json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


class DashboardBroadcaster:
    """
    Fan-out broadcaster for real-time cost dashboard SSE streams.

    Each subscriber gets their own asyncio.Queue.  When broadcast() is called
    the payload is copied to every queue.  The heartbeat_loop() periodically
    pushes spend snapshots so clients stay up to date even when there are no
    LLM calls.
    """

    def __init__(
        self,
        guard: Optional[BudgetGuard] = None,
        push_interval: float = _PUSH_INTERVAL,
        max_connections: int = _MAX_CONNECTIONS,
    ) -> None:
        self._guard = guard
        self._push_interval = push_interval
        self._max_connections = max_connections
        self._queues: List[asyncio.Queue[Optional[str]]] = []
        self._lock = asyncio.Lock()
        self._heartbeat_task: Optional[asyncio.Task[None]] = None

    # ── Public helpers ──────────────────────────────────────────────────────

    @property
    def connection_count(self) -> int:
        return len(self._queues)

    def attach_guard(self, guard: BudgetGuard) -> None:
        """Attach a BudgetGuard after construction (e.g. from app.state)."""
        self._guard = guard
        guard.add_alert_callback(self.on_alert)

    # ── Broadcast ───────────────────────────────────────────────────────────

    async def broadcast(self, data: Dict[str, Any], event: str = "budget") -> None:
        """Push *data* to every active subscriber queue."""
        message = _encode_sse(data, event=event)
        async with self._lock:
            queues = list(self._queues)
        for q in queues:
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                logger.debug("[Dashboard] Subscriber queue full — dropping message.")

    async def broadcast_snapshot(
        self,
        window: BudgetWindow = BudgetWindow.DAILY,
    ) -> None:
        """Pull a fresh snapshot from the attached guard and broadcast it."""
        if self._guard is None:
            payload: Dict[str, Any] = {"type": "snapshot", "timestamp": time.time()}
        else:
            snap: SpendSnapshot = self._guard.current_spend(window)
            payload = {
                "type": "snapshot",
                "timestamp": time.time(),
                "window": window.value,
                **snap.model_dump(),
            }
        await self.broadcast(payload, event="budget")

    async def on_alert(
        self,
        policy: BudgetPolicy,
        alert: BudgetAlert,
        snap: SpendSnapshot,
    ) -> None:
        """AlertCallback — fires immediately when BudgetGuard triggers a threshold.

        register with:  guard.add_alert_callback(broadcaster.on_alert)
        """
        payload: Dict[str, Any] = {
            "type": "alert",
            "timestamp": time.time(),
            "policy": policy.name,
            "level": alert.level.value,
            "action": alert.action.value,
            "pct_threshold": alert.pct_threshold,
            "total_cost_usd": snap.total_cost_usd,
            "limit_usd": policy.limit_usd,
        }
        await self.broadcast(payload, event="alert")

    # ── Subscribe ───────────────────────────────────────────────────────────

    async def subscribe(
        self,
        window: BudgetWindow = BudgetWindow.DAILY,
        queue_size: int = 100,
    ) -> AsyncGenerator[str, None]:
        """
        Async generator that yields SSE-formatted strings.

        Raises RuntimeError if max_connections is already reached.
        Cleans up the queue when the generator is closed (client disconnects).
        """
        if len(self._queues) >= self._max_connections:
            raise RuntimeError(
                f"[Dashboard] Max connections ({self._max_connections}) reached."
            )

        q: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=queue_size)
        async with self._lock:
            self._queues.append(q)

        # Push current snapshot immediately on connect
        if self._guard is not None:
            snap = self._guard.current_spend(window)
            initial: Dict[str, Any] = {
                "type": "snapshot",
                "timestamp": time.time(),
                "window": window.value,
                **snap.model_dump(),
            }
            await q.put(_encode_sse(initial, event="budget"))

        try:
            while True:
                message = await q.get()
                if message is None:
                    break
                yield message
        finally:
            async with self._lock:
                try:
                    self._queues.remove(q)
                except ValueError:
                    pass

    # ── Heartbeat loop ──────────────────────────────────────────────────────

    async def heartbeat_loop(
        self,
        window: BudgetWindow = BudgetWindow.DAILY,
    ) -> None:
        """
        Background task: push a snapshot every push_interval seconds.
        Should be started as an asyncio.Task and cancelled on shutdown.
        """
        while True:
            await asyncio.sleep(self._push_interval)
            if self._queues:  # Skip broadcast if no subscribers
                await self.broadcast_snapshot(window)

    def start_heartbeat(self, window: BudgetWindow = BudgetWindow.DAILY) -> asyncio.Task[None]:
        """Convenience: create and store the heartbeat task."""
        self._heartbeat_task = asyncio.create_task(
            self.heartbeat_loop(window), name="dashboard_heartbeat"
        )
        return self._heartbeat_task

    async def stop(self) -> None:
        """Graceful shutdown: cancel heartbeat and signal all subscribers to close."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        async with self._lock:
            queues = list(self._queues)
        for q in queues:
            await q.put(None)  # sentinel — close the generator
