"""Phase 13 — Enterprise Cost Governance & Budget Guardrails — Test Suite.

All tests are fully self-contained; no real LLM/network calls.
Covers:
  - Cost calculation accuracy (with/without Anthropic cache)
  - Ledger append, tamper-evident chain, snapshot, window queries
  - Policy construction, alert thresholds, utilization helpers
  - BudgetGuard pre_call_check: block, downgrade, session/tier limits
  - BudgetGuard post_call_record + callback firing
  - Edge cases: zero-cost models, missing price table, huge token counts
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ["IRONCORE_EDITION"] = "enterprise"

from ironcore.enterprise.budget.ledger import (
    MODEL_PRICE_TABLE,
    BudgetExceededError,
    BudgetLedger,
    LedgerEntry,
    ModelTier,
    SpendSnapshot,
    _lookup_price,
    calculate_cost,
)
from ironcore.enterprise.budget.policy import (
    AlertLevel,
    BudgetAlert,
    BudgetPolicy,
    BudgetWindow,
    ThrottleAction,
    _WINDOW_SECONDS,
)
from ironcore.enterprise.budget.guard import BudgetGuard


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _policy(
    name: str = "test",
    limit_usd: float = 10.0,
    window: BudgetWindow = BudgetWindow.DAILY,
    alerts: list = None,
    session_limit: float = 0.0,
    tier_limits: dict = None,
) -> BudgetPolicy:
    return BudgetPolicy(
        name=name,
        limit_usd=limit_usd,
        window=window,
        session_limit_usd=session_limit,
        tier_limits=tier_limits or {},
        alerts=alerts or [
            BudgetAlert(pct_threshold=80.0,  level=AlertLevel.WARN,  action=ThrottleAction.LOG),
            BudgetAlert(pct_threshold=100.0, level=AlertLevel.BLOCK, action=ThrottleAction.BLOCK),
        ],
    )


async def _record(ledger: BudgetLedger, model: str = "gpt-4o-mini",
                  inp: int = 1000, out: int = 500, sess: str = "s1") -> LedgerEntry:
    return await ledger.record(
        session_id=sess,
        model_id=model,
        input_tokens=inp,
        output_tokens=out,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  TestCostCalculation
# ══════════════════════════════════════════════════════════════════════════════

class TestCostCalculation:
    def test_gpt4o_mini_basic(self) -> None:
        cost, savings, tier = calculate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
        # input: $0.15, output: $0.60 → total $0.75
        assert abs(cost - 0.75) < 1e-6
        assert tier == ModelTier.MINI
        assert savings == 0.0

    def test_claude_opus_basic(self) -> None:
        cost, _, tier = calculate_cost("claude-3-opus", 1_000_000, 1_000_000)
        # input: $15, output: $75 → $90
        assert abs(cost - 90.0) < 1e-4
        assert tier == ModelTier.PREMIUM

    def test_zero_tokens(self) -> None:
        cost, savings, _ = calculate_cost("gpt-4o", 0, 0)
        assert cost == 0.0
        assert savings == 0.0

    def test_free_local_model(self) -> None:
        cost, savings, tier = calculate_cost("ollama/llama3", 1_000_000, 1_000_000)
        assert cost == 0.0
        assert tier == ModelTier.NANO

    def test_unknown_model_no_crash(self) -> None:
        cost, _, tier = calculate_cost("totally-unknown-model-xyz", 1000, 1000)
        assert cost == 0.0
        assert tier == ModelTier.UNKNOWN

    def test_anthropic_cache_read_cheaper_than_full(self) -> None:
        # Same content billed via cache-read should cost LESS than standard input
        cost_full,    _, _ = calculate_cost("claude-3-5-sonnet", 0, 0, cache_write_tokens=1_000_000)
        cost_standard, _, _ = calculate_cost("claude-3-5-sonnet", 1_000_000, 0)
        # cache write  is 1.25× → more expensive; cache read is 0.10× → cheaper
        cost_read,    savings, _ = calculate_cost("claude-3-5-sonnet", 0, 0, cache_read_tokens=1_000_000)
        assert cost_read < cost_standard
        assert savings > 0.0

    def test_anthropic_cache_write_surcharge(self) -> None:
        cost_write, _, _ = calculate_cost("claude-3-5-sonnet", 0, 0, cache_write_tokens=1_000_000)
        cost_standard, _, _ = calculate_cost("claude-3-5-sonnet", 1_000_000, 0)
        # write should be 25% more expensive than standard input
        assert cost_write > cost_standard

    def test_prefix_matching_works(self) -> None:
        # "claude-3-7-sonnet-20260301" should match "claude-3-7-sonnet" prefix
        cost, _, tier = calculate_cost("claude-3-7-sonnet-20260301", 1_000_000, 0)
        expected_rate = MODEL_PRICE_TABLE["claude-3-7-sonnet"]["input"]
        assert abs(cost - expected_rate) < 1e-6
        assert tier == ModelTier.STANDARD

    def test_lookup_returns_dict(self) -> None:
        result = _lookup_price("gpt-4o")
        assert isinstance(result, dict)
        assert "input" in result
        assert "output" in result

    def test_large_token_count_no_overflow(self) -> None:
        cost, _, _ = calculate_cost("gpt-4o", 10_000_000, 10_000_000)
        expected = (10.0 * 2.5) + (10.0 * 10.0)   # 10M tokens at $2.50/$10 per 1M
        assert abs(cost - expected) < 1e-3


# ══════════════════════════════════════════════════════════════════════════════
#  TestBudgetLedger
# ══════════════════════════════════════════════════════════════════════════════

class TestBudgetLedger:
    @pytest.fixture
    def ledger(self) -> BudgetLedger:
        return BudgetLedger()

    @pytest.mark.asyncio
    async def test_record_appends_entry(self, ledger: BudgetLedger) -> None:
        entry = await _record(ledger)
        assert len(ledger) == 1
        assert entry.model_id == "gpt-4o-mini"
        assert entry.session_id == "s1"

    @pytest.mark.asyncio
    async def test_cost_is_non_negative(self, ledger: BudgetLedger) -> None:
        entry = await _record(ledger)
        assert entry.cost_usd >= 0.0

    @pytest.mark.asyncio
    async def test_entries_are_immutable(self, ledger: BudgetLedger) -> None:
        entry = await _record(ledger)
        with pytest.raises(Exception):
            entry.cost_usd = 999.0   # frozen model → should raise

    @pytest.mark.asyncio
    async def test_snapshot_totals(self, ledger: BudgetLedger) -> None:
        for _ in range(5):
            await _record(ledger, "gpt-4o-mini", 1000, 500)
        snap = ledger.snapshot()
        assert snap.entry_count == 5
        assert snap.total_input_tokens == 5000
        assert snap.total_output_tokens == 2500
        assert snap.total_cost_usd > 0.0

    @pytest.mark.asyncio
    async def test_snapshot_by_model(self, ledger: BudgetLedger) -> None:
        await _record(ledger, "gpt-4o-mini", 1000, 500)
        await _record(ledger, "gpt-4o", 1000, 500)
        snap = ledger.snapshot()
        assert "gpt-4o-mini" in snap.by_model
        assert "gpt-4o" in snap.by_model
        # gpt-4o should cost more than gpt-4o-mini
        assert snap.by_model["gpt-4o"] > snap.by_model["gpt-4o-mini"]

    @pytest.mark.asyncio
    async def test_snapshot_by_session(self, ledger: BudgetLedger) -> None:
        await ledger.record(session_id="alice", model_id="gpt-4o-mini",
                            input_tokens=1000, output_tokens=500)
        await ledger.record(session_id="bob", model_id="gpt-4o-mini",
                            input_tokens=1000, output_tokens=500)
        snap = ledger.snapshot()
        assert "alice" in snap.by_session
        assert "bob" in snap.by_session
        assert abs(snap.by_session["alice"] - snap.by_session["bob"]) < 1e-10

    @pytest.mark.asyncio
    async def test_windowed_snapshot_filters_old_events(self, ledger: BudgetLedger) -> None:
        # Record two entries; filter them by a future timestamp
        await _record(ledger)
        await _record(ledger)
        future_ts = time.time() + 3600  # 1 hour ahead
        snap = ledger.snapshot(since_ts=future_ts)
        assert snap.entry_count == 0

    @pytest.mark.asyncio
    async def test_windowed_snapshot_includes_recent(self, ledger: BudgetLedger) -> None:
        await _record(ledger)
        past_ts = time.time() - 3600
        snap = ledger.snapshot(since_ts=past_ts)
        assert snap.entry_count == 1

    @pytest.mark.asyncio
    async def test_chain_integrity_valid(self, ledger: BudgetLedger) -> None:
        for _ in range(5):
            await _record(ledger)
        assert ledger.verify_chain() is True

    @pytest.mark.asyncio
    async def test_chain_integrity_detects_tamper(self, ledger: BudgetLedger) -> None:
        for _ in range(3):
            await _record(ledger)
        # Tamper directly with internal list (bypass frozen model via __setattr__ on list item)
        # We must replace the entry since it's frozen
        entries = list(ledger._entries)
        tampered = LedgerEntry(
            entry_id=entries[1].entry_id,
            timestamp=entries[1].timestamp,
            session_id=entries[1].session_id,
            model_id=entries[1].model_id,
            tier=entries[1].tier,
            input_tokens=999_999,   # tampered
            output_tokens=entries[1].output_tokens,
            cost_usd=entries[1].cost_usd,
            prev_hash=entries[1].prev_hash,
            entry_hash=entries[1].entry_hash,  # hash not recomputed → mismatch
        )
        ledger._entries[1] = tampered
        assert ledger.verify_chain() is False

    @pytest.mark.asyncio
    async def test_projected_cost_does_not_record(self, ledger: BudgetLedger) -> None:
        _ = ledger.projected_cost("gpt-4o", 1000, 500)
        assert len(ledger) == 0

    @pytest.mark.asyncio
    async def test_concurrent_records_no_race(self, ledger: BudgetLedger) -> None:
        tasks = [_record(ledger, model="gpt-4o-mini") for _ in range(20)]
        await asyncio.gather(*tasks)
        assert len(ledger) == 20
        assert ledger.verify_chain() is True

    @pytest.mark.asyncio
    async def test_cache_savings_tracked(self, ledger: BudgetLedger) -> None:
        await ledger.record(
            session_id="s1",
            model_id="claude-3-5-sonnet",
            input_tokens=0,
            output_tokens=500,
            cache_write_tokens=1000,
            cache_read_tokens=5000,
        )
        snap = ledger.snapshot()
        assert snap.total_cache_write_tokens == 1000
        assert snap.total_cache_read_tokens == 5000
        assert snap.cache_savings_usd >= 0.0

    @pytest.mark.asyncio
    async def test_trace_id_stored(self, ledger: BudgetLedger) -> None:
        entry = await ledger.record(
            session_id="s1", model_id="gpt-4o",
            input_tokens=100, output_tokens=50,
            trace_id="my-trace-123",
        )
        assert entry.trace_id == "my-trace-123"


# ══════════════════════════════════════════════════════════════════════════════
#  TestBudgetPolicy
# ══════════════════════════════════════════════════════════════════════════════

class TestBudgetPolicy:
    def test_default_dev_policy_valid(self) -> None:
        p = BudgetPolicy.default_dev()
        assert p.limit_usd == 10.0
        assert p.window == BudgetWindow.DAILY
        assert len(p.alerts) >= 2

    def test_default_prod_policy_valid(self) -> None:
        p = BudgetPolicy.default_prod()
        assert p.limit_usd == 100.0
        assert p.window == BudgetWindow.MONTHLY
        assert p.session_limit_usd > 0
        assert "premium" in p.tier_limits

    def test_alerts_sorted_ascending(self) -> None:
        p = BudgetPolicy(
            name="t",
            limit_usd=10.0,
            alerts=[
                BudgetAlert(pct_threshold=100.0, level=AlertLevel.BLOCK,  action=ThrottleAction.BLOCK),
                BudgetAlert(pct_threshold=50.0,  level=AlertLevel.INFO,   action=ThrottleAction.LOG),
                BudgetAlert(pct_threshold=80.0,  level=AlertLevel.WARN,   action=ThrottleAction.LOG),
            ],
        )
        thresholds = [a.pct_threshold for a in p.alerts]
        assert thresholds == sorted(thresholds)

    def test_utilization_pct(self) -> None:
        p = _policy(limit_usd=100.0)
        assert p.utilization_pct(50.0) == 50.0
        assert p.utilization_pct(0.0) == 0.0
        assert p.utilization_pct(100.0) == 100.0
        assert p.utilization_pct(120.0) == 120.0

    def test_triggered_alerts_none_when_under_threshold(self) -> None:
        p = _policy(limit_usd=100.0)
        alerts = p.triggered_alerts(50.0)  # 50% < 80% threshold
        assert alerts == []

    def test_triggered_alerts_warn_at_80pct(self) -> None:
        p = _policy(limit_usd=100.0)
        alerts = p.triggered_alerts(80.0)
        assert len(alerts) == 1
        assert alerts[0].level == AlertLevel.WARN

    def test_triggered_alerts_block_at_100pct(self) -> None:
        p = _policy(limit_usd=100.0)
        alerts = p.triggered_alerts(100.0)
        # Both 80% and 100% should fire
        assert len(alerts) == 2
        assert alerts[-1].level == AlertLevel.BLOCK

    def test_highest_triggered_is_block(self) -> None:
        p = _policy(limit_usd=100.0)
        alert = p.highest_triggered(105.0)
        assert alert is not None
        assert alert.level == AlertLevel.BLOCK

    def test_highest_triggered_is_none_below_threshold(self) -> None:
        p = _policy(limit_usd=100.0)
        assert p.highest_triggered(10.0) is None

    def test_window_start_ts_hourly(self) -> None:
        p = _policy(window=BudgetWindow.HOURLY)
        ts = p.window_start_ts()
        assert abs((time.time() - ts) - 3600.0) < 5.0

    def test_window_start_ts_session_is_zero(self) -> None:
        p = _policy(window=BudgetWindow.SESSION)
        assert p.window_start_ts() == 0.0

    def test_block_level_forces_block_action(self) -> None:
        alert = BudgetAlert(
            pct_threshold=100.0,
            level=AlertLevel.BLOCK,
            action=ThrottleAction.LOG,   # should be overridden
        )
        assert alert.action == ThrottleAction.BLOCK

    def test_policy_disabled_not_included(self) -> None:
        p = BudgetPolicy(name="off", limit_usd=5.0, enabled=False)
        guard = BudgetGuard(ledger=BudgetLedger(), policies=[p])
        assert len(guard._policies) == 0

    def test_window_seconds_mapping_complete(self) -> None:
        for window in BudgetWindow:
            assert window in _WINDOW_SECONDS


# ══════════════════════════════════════════════════════════════════════════════
#  TestBudgetGuard
# ══════════════════════════════════════════════════════════════════════════════

class TestBudgetGuard:
    @pytest.fixture
    def ledger(self) -> BudgetLedger:
        return BudgetLedger()

    def _guard(self, ledger: BudgetLedger, limit_usd: float = 1.0,
               session_limit: float = 0.0, tier_limits: dict = None) -> BudgetGuard:
        return BudgetGuard(
            ledger=ledger,
            policies=[_policy(limit_usd=limit_usd,
                               session_limit=session_limit,
                               tier_limits=tier_limits or {})],
        )

    @pytest.mark.asyncio
    async def test_pre_call_passes_under_limit(self, ledger: BudgetLedger) -> None:
        guard = self._guard(ledger, limit_usd=100.0)
        # Should not raise
        await guard.pre_call_check(
            session_id="s1", model_id="gpt-4o-mini",
            estimated_input_tokens=100, estimated_output_tokens=50,
        )

    @pytest.mark.asyncio
    async def test_pre_call_blocks_over_limit(self, ledger: BudgetLedger) -> None:
        # Fill ledger to 100%: gpt-4o at $2.50/$10 per 1M tokens
        # ~$1 = 100M input tokens at $0.0000025 each  → use 400_000 input to get ~$1
        await ledger.record(
            session_id="s1", model_id="gpt-4o",
            input_tokens=400_000, output_tokens=0,
        )
        guard = self._guard(ledger, limit_usd=1.0)
        with pytest.raises(BudgetExceededError) as exc_info:
            await guard.pre_call_check(
                session_id="s1", model_id="gpt-4o",
                estimated_input_tokens=100_000, estimated_output_tokens=50_000,
            )
        assert "test" in exc_info.value.policy_name

    @pytest.mark.asyncio
    async def test_pre_call_no_policies_always_passes(self, ledger: BudgetLedger) -> None:
        guard = BudgetGuard(ledger=ledger, policies=[])
        # Should not raise even with enormous tokens
        await guard.pre_call_check(
            session_id="s1", model_id="claude-3-opus",
            estimated_input_tokens=99_999_999, estimated_output_tokens=99_999_999,
        )

    @pytest.mark.asyncio
    async def test_session_limit_blocks(self, ledger: BudgetLedger) -> None:
        guard = self._guard(ledger, limit_usd=100.0, session_limit=0.001)
        # First heavy call should exceed $0.001 session limit
        with pytest.raises(BudgetExceededError) as exc_info:
            await guard.pre_call_check(
                session_id="s1", model_id="gpt-4o",
                estimated_input_tokens=5000, estimated_output_tokens=1000,
            )
        assert "session" in exc_info.value.policy_name

    @pytest.mark.asyncio
    async def test_tier_limit_blocks_premium(self, ledger: BudgetLedger) -> None:
        guard = self._guard(ledger, limit_usd=1000.0, tier_limits={"premium": 0.001})
        with pytest.raises(BudgetExceededError) as exc_info:
            await guard.pre_call_check(
                session_id="s1", model_id="claude-3-opus",
                estimated_input_tokens=5000, estimated_output_tokens=1000,
            )
        assert "tier:premium" in exc_info.value.policy_name

    @pytest.mark.asyncio
    async def test_post_call_record_stores_entry(self, ledger: BudgetLedger) -> None:
        guard = self._guard(ledger, limit_usd=100.0)
        await guard.post_call_record(
            session_id="s1", model_id="gpt-4o-mini",
            input_tokens=1000, output_tokens=500,
        )
        assert len(ledger) == 1

    @pytest.mark.asyncio
    async def test_post_call_fires_alert_callback(self, ledger: BudgetLedger) -> None:
        fired: List[dict] = []

        async def on_alert(policy, alert, snap):
            fired.append({"policy": policy.name, "level": alert.level.value})

        # Set budget so we are already at warn level after one record
        policy = BudgetPolicy(
            name="narrow",
            limit_usd=0.00001,   # tiny limit — any real call exceeds it
            window=BudgetWindow.SESSION,
            alerts=[
                BudgetAlert(pct_threshold=1.0, level=AlertLevel.WARN, action=ThrottleAction.LOG),
            ],
        )
        guard = BudgetGuard(ledger=ledger, policies=[policy], alert_callbacks=[on_alert])
        await guard.post_call_record(
            session_id="s1", model_id="gpt-4o-mini",
            input_tokens=1000, output_tokens=500,
        )
        assert len(fired) > 0
        assert fired[0]["policy"] == "narrow"

    @pytest.mark.asyncio
    async def test_add_policy_dynamically(self, ledger: BudgetLedger) -> None:
        guard = BudgetGuard(ledger=ledger, policies=[])
        assert len(guard._policies) == 0
        guard.add_policy(_policy(limit_usd=5.0))
        assert len(guard._policies) == 1

    @pytest.mark.asyncio
    async def test_current_spend_returns_snapshot(self, ledger: BudgetLedger) -> None:
        guard = self._guard(ledger, limit_usd=100.0)
        await guard.post_call_record(
            session_id="s1", model_id="gpt-4o-mini",
            input_tokens=500, output_tokens=200,
        )
        snap = guard.current_spend(BudgetWindow.DAILY)
        assert isinstance(snap, SpendSnapshot)
        assert snap.total_cost_usd > 0.0

    @pytest.mark.asyncio
    async def test_guard_exposes_ledger(self, ledger: BudgetLedger) -> None:
        guard = self._guard(ledger)
        assert guard.ledger is ledger

    @pytest.mark.asyncio
    async def test_alert_callback_exception_does_not_propagate(self, ledger: BudgetLedger) -> None:
        async def bad_cb(policy, alert, snap):
            raise RuntimeError("oops")

        policy = BudgetPolicy(
            name="test-cb-err",
            limit_usd=0.000001,
            window=BudgetWindow.SESSION,
            alerts=[BudgetAlert(pct_threshold=1.0, level=AlertLevel.WARN, action=ThrottleAction.LOG)],
        )
        guard = BudgetGuard(ledger=ledger, policies=[policy], alert_callbacks=[bad_cb])
        # Should not raise despite bad callback
        await guard.post_call_record(
            session_id="s1", model_id="gpt-4o-mini",
            input_tokens=1000, output_tokens=500,
        )

    @pytest.mark.asyncio
    async def test_budget_exceeded_error_attributes(self) -> None:
        err = BudgetExceededError(
            policy_name="test-pol",
            limit_usd=10.0,
            projected_usd=11.5,
            window="daily",
        )
        assert err.policy_name == "test-pol"
        assert err.limit_usd == 10.0
        assert err.projected_usd == 11.5
        assert err.window == "daily"
        assert "test-pol" in str(err)


# ══════════════════════════════════════════════════════════════════════════════
#  TestBudgetIntegration — simulated multi-session scenario
# ══════════════════════════════════════════════════════════════════════════════

class TestBudgetIntegration:
    @pytest.mark.asyncio
    async def test_multi_session_spend_tracked_independently(self) -> None:
        ledger = BudgetLedger()
        for _ in range(3):
            await ledger.record(session_id="alice", model_id="gpt-4o-mini",
                                input_tokens=1000, output_tokens=500)
        for _ in range(5):
            await ledger.record(session_id="bob", model_id="gpt-4o-mini",
                                input_tokens=1000, output_tokens=500)

        snap = ledger.snapshot()
        assert snap.by_session["alice"] < snap.by_session["bob"]
        assert snap.entry_count == 8

    @pytest.mark.asyncio
    async def test_spend_accumulates_across_calls(self) -> None:
        ledger = BudgetLedger()
        guard = BudgetGuard(
            ledger=ledger,
            policies=[_policy(limit_usd=10000.0)],
        )
        for i in range(10):
            await guard.post_call_record(
                session_id="s1", model_id="gpt-4o",
                input_tokens=10_000, output_tokens=5_000,
            )
        snap = guard.current_spend(BudgetWindow.DAILY)
        assert snap.entry_count == 10
        cost_per_call = ledger.projected_cost("gpt-4o", 10_000, 5_000)
        assert abs(snap.total_cost_usd - cost_per_call * 10) < 1e-8

    @pytest.mark.asyncio
    async def test_free_model_never_triggers_budget(self) -> None:
        ledger = BudgetLedger()
        guard = BudgetGuard(
            ledger=ledger,
            policies=[_policy(limit_usd=0.001)],  # tiny limit
        )
        # Should pass for free local model regardless of token count
        for _ in range(50):
            await guard.pre_call_check(
                session_id="s1", model_id="ollama/llama3",
                estimated_input_tokens=1_000_000, estimated_output_tokens=1_000_000,
            )

    @pytest.mark.asyncio
    async def test_default_dev_factory_works_end_to_end(self) -> None:
        ledger = BudgetLedger()
        guard = BudgetGuard(
            ledger=ledger,
            policies=[BudgetPolicy.default_dev()],
        )
        # Small calls should not raise
        for _ in range(5):
            await guard.pre_call_check(
                session_id="s1", model_id="gpt-4o-mini",
                estimated_input_tokens=100, estimated_output_tokens=50,
            )
            await guard.post_call_record(
                session_id="s1", model_id="gpt-4o-mini",
                input_tokens=100, output_tokens=50,
            )
        snap = guard.current_spend(BudgetWindow.DAILY)
        assert snap.total_cost_usd < 10.0   # well under $10 limit

    @pytest.mark.asyncio
    async def test_chain_integrity_after_many_records(self) -> None:
        ledger = BudgetLedger()
        for _ in range(30):
            await ledger.record(
                session_id="s1", model_id="gpt-4o",
                input_tokens=500, output_tokens=200,
            )
        assert ledger.verify_chain() is True
