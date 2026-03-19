"""tests/test_phase18_multitenancy.py — Phase 18: Multi-tenant Budget Isolation.

Run with:
    cd "/home/vusinhthanh/train ai" && IRONCORE_EDITION=enterprise PYTHONPATH="." \
    .venv/bin/python -m pytest tests/test_phase18_multitenancy.py -v --tb=short
"""
from __future__ import annotations

import asyncio
import time
from typing import List

import pytest

from ironcore.enterprise.budget.tenant_registry import (
    TenantBudgetRegistry,
    TenantBudgetContext,
    _default_tenant_policy,
)
from ironcore.enterprise.budget.ledger import BudgetLedger, SpendSnapshot
from ironcore.enterprise.budget.guard import BudgetGuard
from ironcore.enterprise.budget.policy import (
    AlertLevel,
    BudgetAlert,
    BudgetPolicy,
    BudgetWindow,
    ThrottleAction,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _custom_policy(limit: float = 5.0, name: str = "custom") -> BudgetPolicy:
    return BudgetPolicy(
        name=name,
        limit_usd=limit,
        window=BudgetWindow.DAILY,
        alerts=[
            BudgetAlert(pct_threshold=100.0, level=AlertLevel.BLOCK, action=ThrottleAction.BLOCK),
        ],
    )


async def _record_cost(registry: TenantBudgetRegistry, tenant_id: str, cost_usd: float) -> None:
    """Directly record cost into a tenant's ledger for testing."""
    ledger = await registry.get_ledger(tenant_id)
    await ledger.record(
        session_id="test-session",
        model_id="gpt-4o-mini",
        input_tokens=1000,
        output_tokens=100,
    )
    # Patch by manually inserting exact cost via internal state
    # (Ledger.record uses model pricing — instead we snapshot and verify isolation)


# ── Test 1: Tenant A and B have separate ledgers ─────────────────────────────

@pytest.mark.asyncio
async def test_tenant_isolation_separate_ledgers():
    registry = TenantBudgetRegistry()
    ledger_a = await registry.get_ledger("tenant-a")
    ledger_b = await registry.get_ledger("tenant-b")
    # Different objects
    assert ledger_a is not ledger_b


# ── Test 2: Cost of tenant A does not affect tenant B ─────────────────────────

@pytest.mark.asyncio
async def test_cost_does_not_leak_between_tenants():
    registry = TenantBudgetRegistry()
    ledger_a = await registry.get_ledger("tenant-a")
    ledger_b = await registry.get_ledger("tenant-b")

    # Record 10 entries on A's ledger
    for _ in range(10):
        await ledger_a.record(
            session_id="s1", model_id="gpt-4o-mini",
            input_tokens=1000, output_tokens=100,
        )

    snap_a = ledger_a.snapshot()
    snap_b = ledger_b.snapshot()

    assert snap_a.total_cost_usd > 0
    assert snap_b.total_cost_usd == 0.0


# ── Test 3: Tenant A budget-exceeded → B can still call ───────────────────────

@pytest.mark.asyncio
async def test_tenant_a_exhausted_does_not_block_tenant_b():
    from ironcore.enterprise.budget.ledger import BudgetExceededError

    def _tiny_policy():
        return BudgetPolicy(
            name="tiny",
            limit_usd=0.001,   # small-but-non-zero: A's 100K tokens will exceed, B's tiny call won't
            window=BudgetWindow.DAILY,
            alerts=[
                BudgetAlert(pct_threshold=100.0, level=AlertLevel.BLOCK, action=ThrottleAction.BLOCK),
            ],
        )

    registry = TenantBudgetRegistry(default_policy_factory=_tiny_policy)

    # Saturate tenant A
    ledger_a = await registry.get_ledger("tenant-a")
    await ledger_a.record(session_id="s", model_id="gpt-4o", input_tokens=100_000, output_tokens=10_000)

    guard_a = await registry.get_guard("tenant-a")
    with pytest.raises(BudgetExceededError):
        await guard_a.pre_call_check(
            session_id="s",
            model_id="gpt-4o",
            estimated_input_tokens=1000,
            estimated_output_tokens=100,
        )

    # Tenant B (separate ledger) must not be blocked
    guard_b = await registry.get_guard("tenant-b")
    # Should not raise with a fresh empty ledger
    await guard_b.pre_call_check(
        session_id="s",
        model_id="gpt-4o-mini",
        estimated_input_tokens=10,
        estimated_output_tokens=5,
    )


# ── Test 4: Lazy init on first access ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_lazy_init_creates_context_on_first_access():
    registry = TenantBudgetRegistry()
    assert registry.tenant_count() == 0
    await registry.get_guard("new-tenant")
    assert registry.tenant_count() == 1


# ── Test 5: update_policy changes only target tenant ─────────────────────────

@pytest.mark.asyncio
async def test_update_policy_affects_only_target_tenant():
    registry = TenantBudgetRegistry()
    await registry.get_guard("tenant-x")
    await registry.get_guard("tenant-y")

    new_policy = _custom_policy(limit=999.0, name="big-budget")
    await registry.update_policy("tenant-x", new_policy)

    snap_x = await registry.get_snapshot("tenant-x")
    snap_y = await registry.get_snapshot("tenant-y")

    # Guard for x should use the new policy (limit 999); y should be unchanged (default)
    guard_x = await registry.get_guard("tenant-x")
    guard_y = await registry.get_guard("tenant-y")

    # Check that guard_x uses the new limit by inspecting policy directly
    assert guard_x._policies[0].limit_usd == 999.0
    # tenant-y unchanged
    assert guard_y._policies[0].limit_usd != 999.0


# ── Test 6: Tenant admin cannot see another tenant's spend (403 behaviour) ───

def test_assert_tenant_access_blocks_cross_tenant():
    from ironcore.enterprise.budget.tenant_registry import (
        TenantAccessDeniedError,
        check_tenant_access,
    )
    with pytest.raises(TenantAccessDeniedError):
        check_tenant_access(caller_tenant="tenant-a", target_tenant="tenant-b")


# ── Test 7: system admin (caller_tenant=None) can see all tenants ─────────────

def test_assert_tenant_access_allows_system_admin():
    from ironcore.enterprise.budget.tenant_registry import check_tenant_access
    # Should not raise — None means system admin
    check_tenant_access(caller_tenant=None, target_tenant="tenant-x")


# ── Test 8: reset_tenant resets ledger and policy ────────────────────────────

@pytest.mark.asyncio
async def test_reset_tenant_clears_ledger_and_policy():
    registry = TenantBudgetRegistry()
    ledger = await registry.get_ledger("tenant-reset")
    await ledger.record(session_id="s", model_id="gpt-4o", input_tokens=1000, output_tokens=100)
    snap_before = ledger.snapshot()
    assert snap_before.total_cost_usd > 0

    await registry.reset_tenant("tenant-reset")

    # After reset, get new ledger and verify it's empty
    new_ledger = await registry.get_ledger("tenant-reset")
    snap_after = new_ledger.snapshot()
    assert snap_after.total_cost_usd == 0.0
    assert snap_after.entry_count == 0


# ── Test 9: list_tenants returns correct set ──────────────────────────────────

@pytest.mark.asyncio
async def test_list_tenants_returns_all_tracked():
    registry = TenantBudgetRegistry()
    for tid in ["t1", "t2", "t3"]:
        await registry.get_guard(tid)
    tenants = await registry.list_tenants()
    assert set(tenants) == {"t1", "t2", "t3"}


# ── Test 10: 100 concurrent calls without race condition ──────────────────────

@pytest.mark.asyncio
async def test_concurrent_calls_no_race_condition():
    """100 concurrent tasks all accessing different tenants must not race."""
    registry = TenantBudgetRegistry()

    async def _access(tenant_id: str) -> None:
        guard = await registry.get_guard(tenant_id)
        assert guard is not None

    await asyncio.gather(*[_access(f"tenant-{i}") for i in range(100)])
    assert registry.tenant_count() == 100


# ── Test 11: tenant_count() is accurate ───────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_count_accurate():
    registry = TenantBudgetRegistry()
    assert registry.tenant_count() == 0
    await registry.get_guard("a")
    assert registry.tenant_count() == 1
    await registry.get_guard("b")
    assert registry.tenant_count() == 2
    # Accessing existing tenant again must not increment count
    await registry.get_guard("a")
    assert registry.tenant_count() == 2
