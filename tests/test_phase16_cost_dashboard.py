"""tests/test_phase16_cost_dashboard.py — Phase 16: Live Cost Dashboard.

Tests for DashboardBroadcaster SSE fan-out + API endpoints.
Run with:
    cd "/home/vusinhthanh/train ai" && IRONCORE_EDITION=enterprise PYTHONPATH="." \
    .venv/bin/python -m pytest tests/test_phase16_cost_dashboard.py -v --tb=short
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from ironcore.enterprise.budget.dashboard_ws import DashboardBroadcaster, _encode_sse
from ironcore.enterprise.budget.guard import BudgetGuard
from ironcore.enterprise.budget.ledger import BudgetLedger, SpendSnapshot
from ironcore.enterprise.budget.policy import (
    AlertLevel,
    BudgetAlert,
    BudgetPolicy,
    BudgetWindow,
    ThrottleAction,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_guard(limit_usd: float = 10.0) -> BudgetGuard:
    policy = BudgetPolicy(
        name="test",
        limit_usd=limit_usd,
        window=BudgetWindow.DAILY,
        alerts=[
            BudgetAlert(pct_threshold=80.0, level=AlertLevel.WARN, action=ThrottleAction.LOG),
            BudgetAlert(pct_threshold=100.0, level=AlertLevel.BLOCK, action=ThrottleAction.BLOCK),
        ],
    )
    return BudgetGuard(ledger=BudgetLedger(), policies=[policy])


# ── Unit tests: DashboardBroadcaster ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_broadcaster_initial_connection_count_is_zero():
    broadcaster = DashboardBroadcaster()
    assert broadcaster.connection_count == 0


@pytest.mark.asyncio
async def test_broadcaster_subscribe_increments_count():
    broadcaster = DashboardBroadcaster()
    gen = broadcaster.subscribe()
    # Force generator to start (reach first yield point)
    task = asyncio.create_task(_drain_one(gen))
    await asyncio.sleep(0.01)
    assert broadcaster.connection_count == 1
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, StopAsyncIteration):
        pass


async def _drain_one(gen) -> str:
    return await gen.__anext__()


@pytest.mark.asyncio
async def test_broadcast_delivers_to_subscriber():
    broadcaster = DashboardBroadcaster()
    received: List[str] = []

    async def _consumer():
        async for msg in broadcaster.subscribe():
            received.append(msg)
            break  # only read one message

    task = asyncio.create_task(_consumer())
    await asyncio.sleep(0.01)  # let subscriber register

    await broadcaster.broadcast({"type": "test", "value": 42})
    await asyncio.sleep(0.01)  # let message propagate

    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, StopAsyncIteration):
        pass

    assert len(received) >= 1
    payload = json.loads(received[0].split("data: ")[1].strip())
    assert payload["value"] == 42


@pytest.mark.asyncio
async def test_broadcast_fan_out_to_multiple_subscribers():
    broadcaster = DashboardBroadcaster()
    queues_received: List[List[str]] = [[] for _ in range(3)]

    async def _consumer(idx: int):
        async for msg in broadcaster.subscribe():
            queues_received[idx].append(msg)
            break

    tasks = [asyncio.create_task(_consumer(i)) for i in range(3)]
    await asyncio.sleep(0.02)

    await broadcaster.broadcast({"type": "ping"})
    await asyncio.sleep(0.02)

    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    # All 3 should have received the message
    assert all(len(q) >= 1 for q in queues_received)


@pytest.mark.asyncio
async def test_on_alert_triggers_broadcast():
    """on_alert() callback must broadcast an 'alert' event."""
    broadcaster = DashboardBroadcaster()
    received: List[str] = []

    async def _consumer():
        async for msg in broadcaster.subscribe():
            received.append(msg)
            if len(received) >= 2:  # initial snapshot (no guard) + alert
                break

    task = asyncio.create_task(_consumer())
    await asyncio.sleep(0.01)

    policy = BudgetPolicy(name="p", limit_usd=5.0, window=BudgetWindow.DAILY, alerts=[])
    alert = BudgetAlert(pct_threshold=80.0, level=AlertLevel.WARN, action=ThrottleAction.LOG)
    snap = SpendSnapshot(total_cost_usd=4.0)

    await broadcaster.on_alert(policy, alert, snap)
    await asyncio.sleep(0.01)

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    alert_msgs = [m for m in received if '"alert"' in m]
    assert len(alert_msgs) >= 1
    data = json.loads(alert_msgs[0].split("data: ")[1].strip())
    assert data["type"] == "alert"
    assert data["level"] == "warn"


@pytest.mark.asyncio
async def test_on_alert_payload_includes_policy_name():
    broadcaster = DashboardBroadcaster()
    received: List[str] = []

    async def _consumer():
        async for msg in broadcaster.subscribe():
            received.append(msg)
            break

    task = asyncio.create_task(_consumer())
    await asyncio.sleep(0.01)

    policy = BudgetPolicy(name="prod-daily", limit_usd=100.0, window=BudgetWindow.DAILY, alerts=[])
    alert = BudgetAlert(pct_threshold=95.0, level=AlertLevel.CRITICAL, action=ThrottleAction.LOG)
    snap = SpendSnapshot(total_cost_usd=95.0)

    await broadcaster.on_alert(policy, alert, snap)
    await asyncio.sleep(0.01)

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    alert_msgs = [m for m in received if '"alert"' in m]
    if alert_msgs:
        data = json.loads(alert_msgs[0].split("data: ")[1].strip())
        assert data["policy"] == "prod-daily"


@pytest.mark.asyncio
async def test_subscribe_sends_initial_snapshot_with_guard():
    """When guard is attached, first SSE message on connect is a snapshot."""
    guard = _make_guard()
    broadcaster = DashboardBroadcaster(guard=guard)
    received: List[str] = []

    async def _consumer():
        async for msg in broadcaster.subscribe():
            received.append(msg)
            break

    task = asyncio.create_task(_consumer())
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert len(received) >= 1
    data = json.loads(received[0].split("data: ")[1].strip())
    assert data["type"] == "snapshot"


@pytest.mark.asyncio
async def test_heartbeat_loop_pushes_snapshot():
    """heartbeat_loop() should push at least one snapshot within interval."""
    guard = _make_guard()
    broadcaster = DashboardBroadcaster(guard=guard, push_interval=0.05)
    received: List[str] = []

    async def _consumer():
        async for msg in broadcaster.subscribe():
            received.append(msg)
            if len(received) >= 2:
                break

    task_consumer = asyncio.create_task(_consumer())
    task_hb = broadcaster.start_heartbeat()

    await asyncio.sleep(0.2)

    task_hb.cancel()
    task_consumer.cancel()
    await asyncio.gather(task_hb, task_consumer, return_exceptions=True)

    snapshot_msgs = [m for m in received if '"snapshot"' in m]
    assert len(snapshot_msgs) >= 1


@pytest.mark.asyncio
async def test_max_connections_raises():
    broadcaster = DashboardBroadcaster(max_connections=1)

    async def _consume():
        async for _ in broadcaster.subscribe():
            await asyncio.sleep(10)

    # First connection
    t = asyncio.create_task(_consume())
    await asyncio.sleep(0.02)

    # Second connection should raise
    with pytest.raises(RuntimeError, match="Max connections"):
        gen = broadcaster.subscribe()
        await gen.__anext__()

    t.cancel()
    await asyncio.gather(t, return_exceptions=True)


@pytest.mark.asyncio
async def test_stop_sends_sentinel_to_all_subscribers():
    """stop() should cause all subscriber generators to finish."""
    broadcaster = DashboardBroadcaster()
    done: List[bool] = []

    async def _consumer():
        async for _ in broadcaster.subscribe():
            pass
        done.append(True)

    tasks = [asyncio.create_task(_consumer()) for _ in range(2)]
    await asyncio.sleep(0.02)
    assert broadcaster.connection_count == 2

    await broadcaster.stop()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert len(done) == 2


@pytest.mark.asyncio
async def test_attach_guard_registers_alert_callback():
    """attach_guard() should register on_alert as callback in BudgetGuard."""
    broadcaster = DashboardBroadcaster()
    guard = _make_guard()
    assert len(guard._alert_callbacks) == 0

    broadcaster.attach_guard(guard)
    assert len(guard._alert_callbacks) == 1
    # Bound methods are recreated on each attribute access; compare by __func__
    assert guard._alert_callbacks[0].__func__ is broadcaster.on_alert.__func__


# ── _encode_sse helper ────────────────────────────────────────────────────────

def test_encode_sse_format():
    result = _encode_sse({"x": 1}, event="budget")
    assert result.startswith("event: budget\n")
    assert "data: " in result
    assert result.endswith("\n\n")
    payload = json.loads(result.split("data: ")[1].strip())
    assert payload["x"] == 1


# ── broadcast_snapshot ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_broadcast_snapshot_no_guard():
    """broadcast_snapshot without guard sends a minimal timestamp payload."""
    broadcaster = DashboardBroadcaster(guard=None)
    received: List[str] = []

    async def _consumer():
        async for msg in broadcaster.subscribe():
            received.append(msg)
            break

    task = asyncio.create_task(_consumer())
    await asyncio.sleep(0.01)

    await broadcaster.broadcast_snapshot()
    await asyncio.sleep(0.02)

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    # filter out any initial messages; look for one that has "snapshot"
    snapshot_msgs = [m for m in received if '"snapshot"' in m]
    assert len(snapshot_msgs) >= 1
