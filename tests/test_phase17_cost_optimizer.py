"""tests/test_phase17_cost_optimizer.py — Phase 17: Autonomous Cost Optimizer.

Tests for CostOptimizer tier waterfall, LLMBridge integration, and alert callbacks.
Run with:
    cd "/home/vusinhthanh/train ai" && IRONCORE_EDITION=enterprise PYTHONPATH="." \
    .venv/bin/python -m pytest tests/test_phase17_cost_optimizer.py -v --tb=short
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ironcore.enterprise.budget.optimizer import (
    CostOptimizer,
    CostOptimizerBlockedError,
    DOWNGRADE_MAP,
    DowngradeLevel,
    SECOND_TIER_MAP,
)
from ironcore.enterprise.budget.ledger import BudgetLedger, SpendSnapshot
from ironcore.enterprise.budget.policy import (
    AlertLevel,
    BudgetAlert,
    BudgetPolicy,
    BudgetWindow,
    ThrottleAction,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _policy(limit: float = 10.0) -> BudgetPolicy:
    return BudgetPolicy(
        name="test",
        limit_usd=limit,
        window=BudgetWindow.DAILY,
        alerts=[
            BudgetAlert(pct_threshold=80.0, level=AlertLevel.WARN, action=ThrottleAction.LOG),
        ],
    )


def _snap(cost: float) -> SpendSnapshot:
    return SpendSnapshot(total_cost_usd=cost)


def _alert(pct: float = 80.0) -> BudgetAlert:
    return BudgetAlert(pct_threshold=pct, level=AlertLevel.WARN, action=ThrottleAction.LOG)


# ── Test 1: Tier-1 downgrade — claude-3-7-sonnet → claude-3-5-haiku ──────────

@pytest.mark.asyncio
async def test_tier1_downgrade_claude_sonnet():
    optimizer = CostOptimizer(tier1_threshold=0.80, tier2_threshold=0.95)
    policy = _policy(limit=10.0)
    # 80% utilization → TIER1
    await optimizer.on_alert(policy, _alert(80.0), _snap(8.0))
    assert optimizer.current_level == DowngradeLevel.TIER1
    effective = optimizer.get_effective_model("claude-3-7-sonnet")
    assert effective == DOWNGRADE_MAP["claude-3-7-sonnet"]
    assert effective == "claude-3-5-haiku"


# ── Test 2: Tier-1 downgrade — gpt-4o → gpt-4o-mini ─────────────────────────

@pytest.mark.asyncio
async def test_tier1_downgrade_gpt4o():
    optimizer = CostOptimizer(tier1_threshold=0.80, tier2_threshold=0.95)
    policy = _policy(limit=10.0)
    await optimizer.on_alert(policy, _alert(80.0), _snap(8.0))
    assert optimizer.get_effective_model("gpt-4o") == "gpt-4o-mini"


# ── Test 3: Tier-1 downgrade — gemini-2.5-pro → gemini-1.5-flash ─────────────

@pytest.mark.asyncio
async def test_tier1_downgrade_gemini():
    optimizer = CostOptimizer(tier1_threshold=0.80, tier2_threshold=0.95)
    policy = _policy(limit=10.0)
    await optimizer.on_alert(policy, _alert(80.0), _snap(8.0))
    assert optimizer.get_effective_model("gemini-2.5-pro") == "gemini-1.5-flash"


# ── Test 4: Tier-2 two-step downgrade at 95% ─────────────────────────────────

@pytest.mark.asyncio
async def test_tier2_double_downgrade():
    optimizer = CostOptimizer(tier1_threshold=0.80, tier2_threshold=0.95)
    policy = _policy(limit=10.0)
    # 95% utilization → TIER2
    await optimizer.on_alert(policy, _alert(95.0), _snap(9.5))
    assert optimizer.current_level == DowngradeLevel.TIER2
    # claude-3-7-sonnet → claude-3-5-haiku (DOWNGRADE_MAP) → claude-3-haiku (SECOND_TIER_MAP)
    effective = optimizer.get_effective_model("claude-3-7-sonnet")
    assert effective == "claude-3-haiku-20240307"


# ── Test 5: BLOCK at ≥ 99% — raises CostOptimizerBlockedError ────────────────

@pytest.mark.asyncio
async def test_block_at_99_percent():
    optimizer = CostOptimizer(tier1_threshold=0.80, tier2_threshold=0.95, block_threshold=0.99)
    policy = _policy(limit=10.0)
    # 99% utilization → BLOCK
    await optimizer.on_alert(policy, _alert(99.0), _snap(9.9))
    assert optimizer.current_level == DowngradeLevel.BLOCK
    with pytest.raises(CostOptimizerBlockedError):
        optimizer.get_effective_model("gpt-4o")


# ── Test 6: Unknown model passes through unchanged ────────────────────────────

@pytest.mark.asyncio
async def test_unknown_model_passthrough():
    optimizer = CostOptimizer(tier1_threshold=0.80, tier2_threshold=0.95)
    policy = _policy(limit=10.0)
    await optimizer.on_alert(policy, _alert(80.0), _snap(8.0))
    # model not in DOWNGRADE_MAP → returned unchanged
    effective = optimizer.get_effective_model("some-custom-model-v1")
    assert effective == "some-custom-model-v1"


# ── Test 7: reset() clears downgrade level back to NONE ──────────────────────

@pytest.mark.asyncio
async def test_reset_clears_level():
    optimizer = CostOptimizer(tier1_threshold=0.80, tier2_threshold=0.95)
    policy = _policy(limit=10.0)
    await optimizer.on_alert(policy, _alert(95.0), _snap(9.5))
    assert optimizer.current_level == DowngradeLevel.TIER2

    optimizer.reset()
    assert optimizer.current_level == DowngradeLevel.NONE
    # After reset, original model returned
    assert optimizer.get_effective_model("claude-3-7-sonnet") == "claude-3-7-sonnet"


# ── Test 8: on_alert level only escalates, never de-escalates ────────────────

@pytest.mark.asyncio
async def test_level_only_escalates():
    optimizer = CostOptimizer(tier1_threshold=0.80, tier2_threshold=0.95)
    policy = _policy(limit=10.0)
    # Escalate to TIER2
    await optimizer.on_alert(policy, _alert(95.0), _snap(9.5))
    assert optimizer.current_level == DowngradeLevel.TIER2
    # Subsequent alert at lower utilization must NOT de-escalate
    await optimizer.on_alert(policy, _alert(80.0), _snap(8.0))
    assert optimizer.current_level == DowngradeLevel.TIER2


# ── Test 9: Disabled optimizer returns original model always ──────────────────

@pytest.mark.asyncio
async def test_disabled_optimizer_passthrough():
    optimizer = CostOptimizer(enabled=False)
    policy = _policy(limit=10.0)
    await optimizer.on_alert(policy, _alert(99.0), _snap(9.9))
    # Even at 99%, disabled optimizer must not change model or raise
    effective = optimizer.get_effective_model("gpt-4o")
    assert effective == "gpt-4o"
    assert optimizer.current_level == DowngradeLevel.NONE


# ── Test 10: LLMBridge.call_llm() uses CostOptimizer effective model ──────────

@pytest.mark.asyncio
async def test_llmbridge_uses_effective_model():
    """LLMBridge should call the downgraded model, not the original."""
    from ironcore.core.llm_bridge import LLMBridge, ModelConfig, LLMResponse

    optimizer = CostOptimizer(tier1_threshold=0.80, tier2_threshold=0.95, enabled=True)
    # Force TIER1 level
    policy = _policy(limit=10.0)
    await optimizer.on_alert(policy, _alert(80.0), _snap(8.0))
    assert optimizer.current_level == DowngradeLevel.TIER1

    bridge = LLMBridge()
    bridge.set_cost_optimizer(optimizer)

    # Patch litellm.acompletion so no real API calls are made
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"tool_name":"finish","args":{},"reasoning":"done"}'
    mock_response.choices[0].finish_reason = "stop"
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 5

    called_with_model: list[str] = []

    async def _fake_acompletion(**kwargs):
        called_with_model.append(kwargs["model"])
        return mock_response

    import litellm
    with patch.object(litellm, "acompletion", side_effect=_fake_acompletion):
        config = ModelConfig(model_id="gpt-4o")
        resp = await bridge.call_llm(
            messages=[{"role": "user", "content": "hello"}],
            model_config=config,
        )

    assert len(called_with_model) == 1
    # Must have called the downgraded model
    assert called_with_model[0] == "gpt-4o-mini"
    assert resp.model_used == "gpt-4o-mini"


# ── Test 11: BLOCK level propagates through LLMBridge as LLMBudgetExceededError

@pytest.mark.asyncio
async def test_llmbridge_block_raises_budget_exceeded_error():
    """When CostOptimizer is BLOCK, LLMBridge.call_llm() must raise LLMBudgetExceededError."""
    from ironcore.core.llm_bridge import LLMBridge, LLMBudgetExceededError, ModelConfig

    optimizer = CostOptimizer(block_threshold=0.99, enabled=True)
    policy = _policy(limit=10.0)
    await optimizer.on_alert(policy, _alert(99.0), _snap(9.9))
    assert optimizer.current_level == DowngradeLevel.BLOCK

    bridge = LLMBridge()
    bridge.set_cost_optimizer(optimizer)

    with pytest.raises(LLMBudgetExceededError, match="blocked"):
        await bridge.call_llm(
            messages=[{"role": "user", "content": "hi"}],
            model_config=ModelConfig(model_id="claude-3-7-sonnet"),
        )
