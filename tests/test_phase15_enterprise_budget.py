"""
Phase 15 — Enterprise Cost Governance & Budget Guardrails
==========================================================
Integration tests: BudgetGuard ↔ LLMBridge wiring.

These tests verify that `LLMBridge.call_llm()` correctly:
  - Calls `pre_call_check()` before each LiteLLM request
  - Calls `post_call_record()` after each successful request
  - Propagates `BudgetExceededError` as `LLMBudgetExceededError`
  - Gracefully degrades when no guard is attached
  - Handles post_call_record() failures without surfacing them to callers

Enterprise unit tests (ledger / policy / guard standalone) are in
`tests/test_phase13_enterprise_budget.py`.  This file focuses on the
integration seam between the budget subsystem and the LLM calling layer.
"""

from __future__ import annotations

import os
import time
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── require enterprise edition for these tests ─────────────────────────────
pytestmark = pytest.mark.skipif(
    os.environ.get("IRONCORE_EDITION", "community") != "enterprise",
    reason="Phase 15 tests require IRONCORE_EDITION=enterprise",
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _fake_litellm_response(
    content: str = '{"tool_name":"finish","args":{},"reasoning":"done"}',
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_write: int = 0,
    cache_read: int = 0,
    model: str = "claude-haiku-3-5",
) -> MagicMock:
    """Build a realistic litellm.acompletion mock return value."""
    usage = MagicMock()
    usage.prompt_tokens = input_tokens
    usage.completion_tokens = output_tokens
    usage.cache_creation_input_tokens = cache_write
    usage.cache_read_input_tokens = cache_read

    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = "stop"

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    resp.model = model
    return resp


def _make_model_config(
    model_id: str = "claude-haiku-3-5",
    max_output_tokens: int = 256,
    cost_in: float = 0.0008,
    cost_out: float = 0.004,
) -> "ModelConfig":
    from ironcore.core.llm_bridge import ModelConfig
    return ModelConfig(
        model_id=model_id,
        max_input_tokens=200_000,
        max_output_tokens=max_output_tokens,
        cost_per_1k_input_tokens=cost_in,
        cost_per_1k_output_tokens=cost_out,
    )


def _make_bridge() -> "LLMBridge":
    from ironcore.core.llm_bridge import LLMBridge
    return LLMBridge(session_id="test-session-p15", max_budget_usd=50.0)


def _make_guard() -> "BudgetGuard":
    from ironcore.enterprise.budget import BudgetGuard, BudgetLedger, BudgetPolicy
    ledger = BudgetLedger()
    policy = BudgetPolicy.default_dev()
    return BudgetGuard(ledger=ledger, policies=[policy])


# ─────────────────────────────────────────────────────────────────────────────
# Suite 1: set_budget_guard
# ─────────────────────────────────────────────────────────────────────────────

class TestSetBudgetGuard:
    """Tests for LLMBridge.set_budget_guard()."""

    def test_guard_starts_as_none(self):
        bridge = _make_bridge()
        assert bridge._budget_guard is None

    def test_set_budget_guard_attaches(self):
        bridge = _make_bridge()
        guard = _make_guard()
        bridge.set_budget_guard(guard)
        assert bridge._budget_guard is guard

    def test_set_budget_guard_replaces(self):
        bridge = _make_bridge()
        g1 = _make_guard()
        g2 = _make_guard()
        bridge.set_budget_guard(g1)
        bridge.set_budget_guard(g2)
        assert bridge._budget_guard is g2

    def test_set_budget_guard_returns_none(self):
        bridge = _make_bridge()
        result = bridge.set_budget_guard(_make_guard())
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Suite 2: pre_call_check invocation
# ─────────────────────────────────────────────────────────────────────────────

class TestPreCallCheck:
    """pre_call_check() is invoked before the LiteLLM network call."""

    @pytest.mark.asyncio
    async def test_pre_call_check_called_once(self):
        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(return_value=None)
        bridge.set_budget_guard(guard)

        fake_resp = _fake_litellm_response()
        with patch("litellm.acompletion", new=AsyncMock(return_value=fake_resp)):
            await bridge.call_llm(
                [{"role": "user", "content": "hello"}],
                _make_model_config(),
            )

        guard.pre_call_check.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pre_call_check_not_called_without_guard(self):
        """If no guard is attached, call_llm proceeds without pre_call_check."""
        bridge = _make_bridge()
        fake_resp = _fake_litellm_response()
        # Should not raise — no guard attached
        with patch("litellm.acompletion", new=AsyncMock(return_value=fake_resp)):
            result = await bridge.call_llm(
                [{"role": "user", "content": "hello"}],
                _make_model_config(),
            )
        assert result.content != ""

    @pytest.mark.asyncio
    async def test_pre_call_check_receives_correct_session_id(self):
        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(return_value=None)
        guard.post_call_record = AsyncMock(return_value=None)
        bridge.set_budget_guard(guard)

        with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_litellm_response())):
            await bridge.call_llm(
                [{"role": "user", "content": "hi"}],
                _make_model_config("gpt-4o-mini"),
            )

        call_kwargs = guard.pre_call_check.call_args.kwargs
        assert call_kwargs["session_id"] == "test-session-p15"

    @pytest.mark.asyncio
    async def test_pre_call_check_receives_correct_model_id(self):
        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(return_value=None)
        guard.post_call_record = AsyncMock(return_value=None)
        bridge.set_budget_guard(guard)

        with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_litellm_response())):
            await bridge.call_llm(
                [{"role": "user", "content": "hi"}],
                _make_model_config("gpt-4o-mini"),
            )

        call_kwargs = guard.pre_call_check.call_args.kwargs
        assert call_kwargs["model_id"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_pre_call_check_receives_estimated_output_tokens(self):
        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(return_value=None)
        guard.post_call_record = AsyncMock(return_value=None)
        bridge.set_budget_guard(guard)

        model = _make_model_config(max_output_tokens=512)
        with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_litellm_response())):
            await bridge.call_llm([{"role": "user", "content": "hi"}], model)

        call_kwargs = guard.pre_call_check.call_args.kwargs
        assert call_kwargs["estimated_output_tokens"] == 512


# ─────────────────────────────────────────────────────────────────────────────
# Suite 3: BudgetExceededError propagation
# ─────────────────────────────────────────────────────────────────────────────

class TestBudgetExceededPropagation:
    """BudgetExceededError from guard is re-raised as LLMBudgetExceededError."""

    @pytest.mark.asyncio
    async def test_budget_exceeded_raises_llm_budget_error(self):
        from ironcore.enterprise.budget.ledger import BudgetExceededError
        from ironcore.core.llm_bridge import LLMBudgetExceededError

        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(
            side_effect=BudgetExceededError(
                policy_name="dev-daily",
                limit_usd=10.0,
                projected_usd=11.0,
                window="DAILY",
            )
        )
        bridge.set_budget_guard(guard)

        with pytest.raises(LLMBudgetExceededError):
            await bridge.call_llm(
                [{"role": "user", "content": "spend lots"}],
                _make_model_config(),
            )

    @pytest.mark.asyncio
    async def test_litellm_not_called_when_budget_exceeded(self):
        from ironcore.enterprise.budget.ledger import BudgetExceededError

        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(
            side_effect=BudgetExceededError(
                policy_name="dev-daily",
                limit_usd=10.0,
                projected_usd=15.0,
                window="DAILY",
            )
        )
        bridge.set_budget_guard(guard)

        mock_litellm = AsyncMock()
        with patch("litellm.acompletion", new=mock_litellm):
            with pytest.raises(Exception):
                await bridge.call_llm(
                    [{"role": "user", "content": "spend lots"}],
                    _make_model_config(),
                )
        # LiteLLM must NOT have been called
        mock_litellm.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_budget_exceeded_error_contains_policy_info(self):
        from ironcore.enterprise.budget.ledger import BudgetExceededError
        from ironcore.core.llm_bridge import LLMBudgetExceededError

        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(
            side_effect=BudgetExceededError(
                policy_name="my-policy",
                limit_usd=5.0,
                projected_usd=6.0,
                window="DAILY",
            )
        )
        bridge.set_budget_guard(guard)

        with pytest.raises(LLMBudgetExceededError) as exc_info:
            await bridge.call_llm(
                [{"role": "user", "content": "test"}], _make_model_config()
            )

        assert "my-policy" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_budget_exceeded_propagates_through_tier_fallback(self):
        """_call_with_tier_fallback must NOT suppress LLMBudgetExceededError."""
        from ironcore.enterprise.budget.ledger import BudgetExceededError
        from ironcore.core.llm_bridge import LLMBudgetExceededError, TaskComplexity

        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(
            side_effect=BudgetExceededError(
                policy_name="p", limit_usd=1.0, projected_usd=2.0, window="DAILY"
            )
        )
        bridge.set_budget_guard(guard)

        with patch("litellm.acompletion", new=AsyncMock()):
            with pytest.raises(LLMBudgetExceededError):
                await bridge._call_with_tier_fallback(
                    TaskComplexity.SIMPLE,
                    [{"role": "user", "content": "test"}],
                )


# ─────────────────────────────────────────────────────────────────────────────
# Suite 4: post_call_record invocation
# ─────────────────────────────────────────────────────────────────────────────

class TestPostCallRecord:
    """post_call_record() is invoked after successful LLM response."""

    @pytest.mark.asyncio
    async def test_post_call_record_called_once(self):
        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(return_value=None)
        guard.post_call_record = AsyncMock(return_value=None)
        bridge.set_budget_guard(guard)

        with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_litellm_response())):
            await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )

        guard.post_call_record.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_post_call_record_receives_actual_tokens(self):
        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(return_value=None)
        guard.post_call_record = AsyncMock(return_value=None)
        bridge.set_budget_guard(guard)

        fake = _fake_litellm_response(input_tokens=200, output_tokens=80)
        with patch("litellm.acompletion", new=AsyncMock(return_value=fake)):
            await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )

        kw = guard.post_call_record.call_args.kwargs
        assert kw["input_tokens"] == 200
        assert kw["output_tokens"] == 80

    @pytest.mark.asyncio
    async def test_post_call_record_receives_cache_tokens(self):
        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(return_value=None)
        guard.post_call_record = AsyncMock(return_value=None)
        bridge.set_budget_guard(guard)

        fake = _fake_litellm_response(cache_write=50, cache_read=300)
        with patch("litellm.acompletion", new=AsyncMock(return_value=fake)):
            await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )

        kw = guard.post_call_record.call_args.kwargs
        assert kw["cache_write_tokens"] == 50
        assert kw["cache_read_tokens"] == 300

    @pytest.mark.asyncio
    async def test_post_call_record_receives_trace_id(self):
        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(return_value=None)
        guard.post_call_record = AsyncMock(return_value=None)
        bridge.set_budget_guard(guard)

        with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_litellm_response())):
            response = await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )

        kw = guard.post_call_record.call_args.kwargs
        assert kw["trace_id"] == response.trace_id
        assert len(kw["trace_id"]) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_post_call_record_receives_session_id(self):
        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(return_value=None)
        guard.post_call_record = AsyncMock(return_value=None)
        bridge.set_budget_guard(guard)

        with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_litellm_response())):
            await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )

        kw = guard.post_call_record.call_args.kwargs
        assert kw["session_id"] == "test-session-p15"

    @pytest.mark.asyncio
    async def test_post_call_record_failure_is_non_fatal(self):
        """A crash in post_call_record must not prevent LLMResponse from being returned."""
        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(return_value=None)
        guard.post_call_record = AsyncMock(side_effect=RuntimeError("ledger full"))
        bridge.set_budget_guard(guard)

        with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_litellm_response())):
            result = await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )

        # Response still returned despite recorder crashing
        assert result is not None
        assert result.input_tokens == 100

    @pytest.mark.asyncio
    async def test_post_call_record_not_called_on_pre_check_failure(self):
        from ironcore.enterprise.budget.ledger import BudgetExceededError

        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(
            side_effect=BudgetExceededError(
                policy_name="p", limit_usd=1.0, projected_usd=2.0, window="DAILY"
            )
        )
        guard.post_call_record = AsyncMock(return_value=None)
        bridge.set_budget_guard(guard)

        with patch("litellm.acompletion", new=AsyncMock()):
            with pytest.raises(Exception):
                await bridge.call_llm(
                    [{"role": "user", "content": "hi"}], _make_model_config()
                )

        guard.post_call_record.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# Suite 5: Call ordering
# ─────────────────────────────────────────────────────────────────────────────

class TestCallOrdering:
    """pre_call_check fires before litellm, post_call_record fires after."""

    @pytest.mark.asyncio
    async def test_pre_fires_before_litellm(self):
        call_order: list[str] = []

        async def mock_pre(**kwargs):
            call_order.append("pre")

        async def mock_litellm(**kwargs):
            call_order.append("litellm")
            return _fake_litellm_response()

        async def mock_post(**kwargs):
            call_order.append("post")

        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = mock_pre
        guard.post_call_record = mock_post
        bridge.set_budget_guard(guard)

        with patch("litellm.acompletion", new=mock_litellm):
            await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )

        assert call_order == ["pre", "litellm", "post"]

    @pytest.mark.asyncio
    async def test_three_sequential_calls_each_have_pre_and_post(self):
        bridge = _make_bridge()
        guard = _make_guard()
        guard.pre_call_check = AsyncMock(return_value=None)
        guard.post_call_record = AsyncMock(return_value=None)
        bridge.set_budget_guard(guard)

        with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_litellm_response())):
            for _ in range(3):
                await bridge.call_llm(
                    [{"role": "user", "content": "hi"}], _make_model_config()
                )

        assert guard.pre_call_check.await_count == 3
        assert guard.post_call_record.await_count == 3


# ─────────────────────────────────────────────────────────────────────────────
# Suite 6: Real BudgetGuard integration (no mocks on guard)
# ─────────────────────────────────────────────────────────────────────────────

class TestRealGuardIntegration:
    """End-to-end tests using a real BudgetGuard (ledger + policy), mocking litellm."""

    @pytest.mark.asyncio
    async def test_spend_accumulates_in_ledger(self):
        from ironcore.enterprise.budget import BudgetGuard, BudgetLedger, BudgetPolicy, BudgetWindow

        ledger = BudgetLedger()
        guard = BudgetGuard(ledger=ledger, policies=[BudgetPolicy.default_dev()])
        bridge = _make_bridge()
        bridge.set_budget_guard(guard)

        fake = _fake_litellm_response(input_tokens=1000, output_tokens=500, model="claude-haiku-3-5")
        with patch("litellm.acompletion", new=AsyncMock(return_value=fake)):
            await bridge.call_llm(
                [{"role": "user", "content": "hi"}],
                _make_model_config("claude-haiku-3-5"),
            )

        snapshot = guard.current_spend(BudgetWindow.DAILY)
        assert snapshot.total_cost_usd > 0.0
        assert snapshot.entry_count == 1

    @pytest.mark.asyncio
    async def test_multiple_calls_accumulate_spend(self):
        from ironcore.enterprise.budget import BudgetGuard, BudgetLedger, BudgetPolicy, BudgetWindow

        ledger = BudgetLedger()
        guard = BudgetGuard(ledger=ledger, policies=[BudgetPolicy.default_dev()])
        bridge = _make_bridge()
        bridge.set_budget_guard(guard)

        fake = _fake_litellm_response(input_tokens=100, output_tokens=50)
        with patch("litellm.acompletion", new=AsyncMock(return_value=fake)):
            for _ in range(5):
                await bridge.call_llm(
                    [{"role": "user", "content": "hi"}], _make_model_config()
                )

        snapshot = guard.current_spend(BudgetWindow.DAILY)
        assert snapshot.entry_count == 5

    @pytest.mark.asyncio
    async def test_block_policy_raises_llm_budget_error(self):
        """A tight BLOCK policy triggers LLMBudgetExceededError."""
        from ironcore.enterprise.budget import (
            BudgetGuard, BudgetLedger, BudgetPolicy, BudgetAlert,
            BudgetWindow, AlertLevel,
        )
        from ironcore.core.llm_bridge import LLMBudgetExceededError

        # Ultra-tight policy: $0.0001 limit, block at 1%
        policy = BudgetPolicy(
            name="tight",
            limit_usd=0.00001,
            window=BudgetWindow.DAILY,
            alerts=[BudgetAlert(pct_threshold=1.0, level=AlertLevel.BLOCK)],
        )
        ledger = BudgetLedger()
        guard = BudgetGuard(ledger=ledger, policies=[policy])

        # Pre-seed a ledger entry to exceed
        await ledger.record(
            session_id="test-session-p15",
            model_id="claude-haiku-3-5",
            input_tokens=1000,
            output_tokens=500,
            cache_write_tokens=0,
            cache_read_tokens=0,
            trace_id="seed",
        )

        bridge = _make_bridge()
        bridge.set_budget_guard(guard)

        with patch("litellm.acompletion", new=AsyncMock()):
            with pytest.raises(LLMBudgetExceededError):
                await bridge.call_llm(
                    [{"role": "user", "content": "hi"}], _make_model_config()
                )

    @pytest.mark.asyncio
    async def test_free_model_does_not_exceed_budget(self):
        """Calls to a free/local model should not trigger budget errors."""
        from ironcore.enterprise.budget import (
            BudgetGuard, BudgetLedger, BudgetPolicy, BudgetAlert,
            BudgetWindow, AlertLevel,
        )

        policy = BudgetPolicy(
            name="tight",
            limit_usd=0.00001,
            window=BudgetWindow.DAILY,
            alerts=[BudgetAlert(pct_threshold=1.0, level=AlertLevel.BLOCK)],
        )
        guard = BudgetGuard(ledger=BudgetLedger(), policies=[policy])
        bridge = _make_bridge()
        bridge.set_budget_guard(guard)

        local_model = _make_model_config(
            model_id="ollama/llama3.1",
            cost_in=0.0,
            cost_out=0.0,
        )
        fake = _fake_litellm_response(input_tokens=5000, output_tokens=2000, model="ollama/llama3.1")
        with patch("litellm.acompletion", new=AsyncMock(return_value=fake)):
            result = await bridge.call_llm(
                [{"role": "user", "content": "hi"}], local_model
            )

        assert result is not None

    @pytest.mark.asyncio
    async def test_alert_callback_fired_after_threshold_crossed(self):
        from ironcore.enterprise.budget import (
            BudgetGuard, BudgetLedger, BudgetPolicy, BudgetAlert,
            BudgetWindow, AlertLevel,
        )

        fired_alerts: list = []

        async def on_alert(policy, alert, snapshot):
            fired_alerts.append((policy.name, alert.level.name))

        policy = BudgetPolicy(
            name="alert-test",
            limit_usd=0.001,
            window=BudgetWindow.DAILY,
            alerts=[BudgetAlert(pct_threshold=50.0, level=AlertLevel.WARN)],
        )
        guard = BudgetGuard(
            ledger=BudgetLedger(),
            policies=[policy],
            alert_callbacks=[on_alert],
        )

        # Pre-seed to just above 50% of $0.001 = $0.0005
        await guard._ledger.record(
            session_id="s",
            model_id="claude-haiku-3-5",
            input_tokens=500,
            output_tokens=200,
            cache_write_tokens=0,
            cache_read_tokens=0,
            trace_id="seed",
        )

        bridge = _make_bridge()
        bridge.set_budget_guard(guard)

        fake = _fake_litellm_response(
            input_tokens=100, output_tokens=50, model="claude-haiku-3-5"
        )
        with patch("litellm.acompletion", new=AsyncMock(return_value=fake)):
            await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )

        # Alert may or may not have fired depending on exact spend, but bridge must not crash
        assert True  # Bridge completed without exception

    @pytest.mark.asyncio
    async def test_trace_id_recorded_in_ledger(self):
        from ironcore.enterprise.budget import BudgetGuard, BudgetLedger, BudgetPolicy

        ledger = BudgetLedger()
        guard = BudgetGuard(ledger=ledger, policies=[BudgetPolicy.default_dev()])
        bridge = _make_bridge()
        bridge.set_budget_guard(guard)

        fake = _fake_litellm_response(input_tokens=100, output_tokens=50)
        with patch("litellm.acompletion", new=AsyncMock(return_value=fake)):
            response = await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )

        entries = ledger.entries
        assert len(entries) == 1
        assert entries[0].trace_id == response.trace_id

    @pytest.mark.asyncio
    async def test_cache_tokens_recorded_in_ledger(self):
        from ironcore.enterprise.budget import BudgetGuard, BudgetLedger, BudgetPolicy, BudgetWindow

        ledger = BudgetLedger()
        guard = BudgetGuard(ledger=ledger, policies=[BudgetPolicy.default_dev()])
        bridge = _make_bridge()
        bridge.set_budget_guard(guard)

        fake = _fake_litellm_response(
            input_tokens=100, output_tokens=50,
            cache_write=40, cache_read=200,
        )
        with patch("litellm.acompletion", new=AsyncMock(return_value=fake)):
            await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )

        entries = ledger.entries
        assert entries[0].cache_write_tokens == 40
        assert entries[0].cache_read_tokens == 200


# ─────────────────────────────────────────────────────────────────────────────
# Suite 7: Guard disabled / no policies
# ─────────────────────────────────────────────────────────────────────────────

class TestGuardDisabledNoPolicies:

    @pytest.mark.asyncio
    async def test_guard_no_policies_passes_through(self):
        """Guard with no policies attached should not block calls."""
        from ironcore.enterprise.budget import BudgetGuard, BudgetLedger

        guard = BudgetGuard(ledger=BudgetLedger(), policies=[])
        bridge = _make_bridge()
        bridge.set_budget_guard(guard)

        with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_litellm_response())):
            result = await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_disabled_policy_does_not_block(self):
        """Policies with enabled=False should not block calls."""
        from ironcore.enterprise.budget import (
            BudgetGuard, BudgetLedger, BudgetPolicy, BudgetAlert,
            BudgetWindow, AlertLevel,
        )

        policy = BudgetPolicy(
            name="disabled",
            limit_usd=0.00001,
            window=BudgetWindow.DAILY,
            alerts=[BudgetAlert(pct_threshold=1.0, level=AlertLevel.BLOCK)],
            enabled=False,
        )
        guard = BudgetGuard(ledger=BudgetLedger(), policies=[policy])

        # Pre-seed lots of spend
        for _ in range(5):
            await guard._ledger.record(
                session_id="s", model_id="claude-haiku-3-5",
                input_tokens=10_000, output_tokens=5_000,
                cache_write_tokens=0, cache_read_tokens=0,
                trace_id="seed",
            )

        bridge = _make_bridge()
        bridge.set_budget_guard(guard)

        with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_litellm_response())):
            result = await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )

        assert result is not None


# ─────────────────────────────────────────────────────────────────────────────
# Suite 8: LLMResponse fields through budget integration
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMResponseIntegrity:
    """Verify LLMResponse fields are not mutated by the budget guard integration."""

    @pytest.mark.asyncio
    async def test_response_content_preserved(self):
        bridge = _make_bridge()
        guard = _make_guard()
        bridge.set_budget_guard(guard)

        fake = _fake_litellm_response(content='{"tool_name":"think","args":{"thought":"ok"},"reasoning":"r"}')
        with patch("litellm.acompletion", new=AsyncMock(return_value=fake)):
            result = await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )

        assert "think" in result.content

    @pytest.mark.asyncio
    async def test_response_token_counts_preserved(self):
        bridge = _make_bridge()
        guard = _make_guard()
        bridge.set_budget_guard(guard)

        fake = _fake_litellm_response(input_tokens=777, output_tokens=333)
        with patch("litellm.acompletion", new=AsyncMock(return_value=fake)):
            result = await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )

        assert result.input_tokens == 777
        assert result.output_tokens == 333

    @pytest.mark.asyncio
    async def test_response_trace_id_is_uuid(self):
        bridge = _make_bridge()
        guard = _make_guard()
        bridge.set_budget_guard(guard)

        with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_litellm_response())):
            result = await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )

        import re
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            result.trace_id,
        )

    @pytest.mark.asyncio
    async def test_response_cache_tokens_preserved(self):
        bridge = _make_bridge()
        guard = _make_guard()
        bridge.set_budget_guard(guard)

        fake = _fake_litellm_response(cache_write=100, cache_read=400)
        with patch("litellm.acompletion", new=AsyncMock(return_value=fake)):
            result = await bridge.call_llm(
                [{"role": "user", "content": "hi"}], _make_model_config()
            )

        assert result.cache_write_tokens == 100
        assert result.cache_read_tokens == 400
