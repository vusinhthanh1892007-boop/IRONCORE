"""Phase 17 — Autonomous Cost Optimizer.

CostOptimizer is an AlertCallback that automatically downgrades the requested
LLM model to a cheaper alternative when budget utilization crosses configured
thresholds.

Waterfall tiers:
    < TIER1_THRESHOLD   → no change
    TIER1 ≤ u < TIER2  → DOWNGRADE_MAP (one step cheaper)
    TIER2 ≤ u < BLOCK  → SECOND_TIER_MAP + DOWNGRADE_MAP (two steps cheaper)
    ≥ BLOCK_THRESHOLD   → raise CostOptimizerBlockedError (no call allowed)

Integration:
    optimizer = CostOptimizer()
    guard.add_alert_callback(optimizer.on_alert)
    bridge.set_cost_optimizer(optimizer)
"""

from __future__ import annotations

import logging
import os
from enum import IntEnum
from typing import Optional

from ironcore.enterprise.budget.ledger import SpendSnapshot
from ironcore.enterprise.budget.policy import BudgetAlert, BudgetPolicy

logger = logging.getLogger(__name__)

# ── Model downgrade maps ────────────────────────────────────────────────────

# Tier-1 downgrade (80–95%): swap expensive model for first cheaper alternative
DOWNGRADE_MAP: dict[str, str] = {
    # Anthropic
    "claude-3-7-sonnet":             "claude-3-5-haiku",
    "claude-3-7-sonnet-20250219":    "claude-3-5-haiku-20241022",
    "claude-3-5-sonnet":             "claude-3-5-haiku",
    "claude-3-5-sonnet-20240620":    "claude-3-5-haiku-20241022",
    "claude-3-opus":                 "claude-3-5-sonnet",
    "claude-3-opus-20240229":        "claude-3-5-sonnet-20240620",
    # OpenAI
    "gpt-4o":                        "gpt-4o-mini",
    "gpt-4-turbo":                   "gpt-4o-mini",
    "gpt-4.5":                       "gpt-4o",
    "o1":                            "gpt-4o",
    # Google
    "gemini-2.5-pro":                "gemini-1.5-flash",
    "gemini-2.0-flash":              "gemini-1.5-flash",
    "gemini-1.5-pro":                "gemini-1.5-flash",
}

# Tier-2 downgrade (95–99%): applied *after* DOWNGRADE_MAP mapping
SECOND_TIER_MAP: dict[str, str] = {
    # Anthropic
    "claude-3-5-haiku":              "claude-3-haiku-20240307",
    "claude-3-5-haiku-20241022":     "claude-3-haiku-20240307",
    "claude-3-5-sonnet":             "claude-3-5-haiku-20241022",
    "claude-3-5-sonnet-20240620":    "claude-3-5-haiku-20241022",
    # OpenAI — gpt-4o-mini is already the cheapest GPT-4-class model
    "gpt-4o-mini":                   "gpt-4o-mini",
    "gpt-4o":                        "gpt-4o-mini",
    # Google
    "gemini-1.5-flash":              "gemini-1.5-flash-8b",
    "gemini-2.0-flash":              "gemini-1.5-flash-8b",
}


# ── Enums & Exceptions ──────────────────────────────────────────────────────

class DowngradeLevel(IntEnum):
    """Current downgrade state of the optimizer."""
    NONE  = 0  # < TIER1_THRESHOLD — no change
    TIER1 = 1  # TIER1 ≤ u < TIER2 — one-step downgrade
    TIER2 = 2  # TIER2 ≤ u < BLOCK — two-step downgrade
    BLOCK = 3  # ≥ BLOCK_THRESHOLD — all calls rejected


class CostOptimizerBlockedError(Exception):
    """
    Raised by get_effective_model() when the optimizer is in BLOCK state
    (budget utilization ≥ block_threshold).

    LLMBridge catches this and re-raises as LLMBudgetExceededError.
    """


# ── Main class ──────────────────────────────────────────────────────────────

class CostOptimizer:
    """
    Autonomous model-tier downgrade engine.

    Registers as a BudgetGuard AlertCallback.  As budget utilization rises,
    automatically swaps every requested model for a cheaper equivalent.

    Typical usage::

        optimizer = CostOptimizer()
        guard.add_alert_callback(optimizer.on_alert)
        bridge.set_cost_optimizer(optimizer)

    The optimizer level only ever increases within a budget window; call
    reset() when the window rolls over to allow full-price models again.
    """

    def __init__(
        self,
        tier1_threshold: float = float(os.environ.get("TIER1_THRESHOLD", "0.80")),
        tier2_threshold: float = float(os.environ.get("TIER2_THRESHOLD", "0.95")),
        block_threshold: float = 0.99,
        enabled: bool = os.environ.get("IRONCORE_COST_OPTIMIZER_ENABLED", "true").lower() != "false",
    ) -> None:
        self._tier1 = tier1_threshold
        self._tier2 = tier2_threshold
        self._block = block_threshold
        self._enabled = enabled
        self._level: DowngradeLevel = DowngradeLevel.NONE

        logger.info(
            "[CostOptimizer] init | enabled=%s tier1=%.0f%% tier2=%.0f%% block=%.0f%%",
            enabled, tier1_threshold * 100, tier2_threshold * 100, block_threshold * 100,
        )

    # ── AlertCallback ────────────────────────────────────────────────────────

    async def on_alert(
        self,
        policy: BudgetPolicy,
        alert: BudgetAlert,
        snap: SpendSnapshot,
    ) -> None:
        """
        AlertCallback — called by BudgetGuard when a threshold is crossed.

        Computes utilization = snap.total_cost_usd / policy.limit_usd and
        escalates the downgrade level accordingly.  Only ever escalates
        (never de-escalates within a budget window).
        """
        if not self._enabled:
            return

        if policy.limit_usd <= 0:
            return

        utilization = snap.total_cost_usd / policy.limit_usd

        new_level = self._level
        if utilization >= self._block:
            new_level = DowngradeLevel.BLOCK
        elif utilization >= self._tier2:
            new_level = DowngradeLevel.TIER2
        elif utilization >= self._tier1:
            new_level = DowngradeLevel.TIER1

        if new_level > self._level:
            logger.warning(
                "[CostOptimizer] Level upgraded %s → %s | utilization=%.1f%% | policy=%s",
                self._level.name, new_level.name, utilization * 100, policy.name,
            )
            self._level = new_level

    # ── Model routing ────────────────────────────────────────────────────────

    def get_effective_model(self, model_id: str) -> str:
        """
        Return the model to actually use after applying downgrade rules.

        Args:
            model_id: The model the caller originally requested.

        Returns:
            Possibly downgraded model identifier string.

        Raises:
            CostOptimizerBlockedError: When level == BLOCK (≥ block_threshold).
        """
        if not self._enabled or self._level == DowngradeLevel.NONE:
            return model_id

        if self._level == DowngradeLevel.BLOCK:
            raise CostOptimizerBlockedError(
                f"[CostOptimizer] All LLM calls blocked: budget utilization ≥ "
                f"{self._block * 100:.0f}%. Call reset() when the budget window rolls over."
            )

        if self._level == DowngradeLevel.TIER1:
            downgraded = DOWNGRADE_MAP.get(model_id, model_id)
            if downgraded != model_id:
                logger.info(
                    "[CostOptimizer] TIER1 downgrade: %s → %s", model_id, downgraded
                )
            return downgraded

        # TIER2: apply DOWNGRADE_MAP first, then SECOND_TIER_MAP
        t1 = DOWNGRADE_MAP.get(model_id, model_id)
        t2 = SECOND_TIER_MAP.get(t1, t1)
        if t2 != model_id:
            logger.info(
                "[CostOptimizer] TIER2 downgrade: %s → %s → %s", model_id, t1, t2
            )
        return t2

    # ── Control ──────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """
        Reset downgrade level to NONE.

        Call this when the budget window rolls over so callers can again use
        full-price models.
        """
        if self._level != DowngradeLevel.NONE:
            logger.info("[CostOptimizer] Reset: %s → NONE", self._level.name)
        self._level = DowngradeLevel.NONE

    # ── Introspection ────────────────────────────────────────────────────────

    @property
    def current_level(self) -> DowngradeLevel:
        """Current downgrade state."""
        return self._level

    @property
    def enabled(self) -> bool:
        return self._enabled
