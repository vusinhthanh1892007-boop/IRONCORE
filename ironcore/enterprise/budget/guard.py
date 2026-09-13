"""Budget Guard — enforcement layer that wraps every LLM call.

The BudgetGuard sits between the caller and the LLM backend:
  1. Pre-call: projects cost; raises BudgetExceededError if any active
     policy would be breached.
  2. Fires alert callbacks for warn/critical/hitl thresholds.
  3. Post-call: records actual cost in the BudgetLedger.

Works with any BudgetLedger + list of BudgetPolicy objects.
Designed to be injected into LLMBridge without coupling to it directly.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ironcore.enterprise.budget.ledger import (
    BudgetExceededError,
    BudgetLedger,
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
)

logger = logging.getLogger(__name__)

# Callback type: receives policy + alert when a threshold is crossed
AlertCallback = Callable[["BudgetPolicy", "BudgetAlert", "SpendSnapshot"], Awaitable[None]]


class BudgetGuard:
    """
    Runtime enforcement of BudgetPolicy rules.

    Typical usage inside LLMBridge::

        guard = BudgetGuard(
            ledger=BudgetLedger(),
            policies=[BudgetPolicy.default_dev()],
        )

        # Before calling the LLM:
        await guard.pre_call_check(
            session_id=session_id,
            model_id=model_config.model_id,
            estimated_input_tokens=len(messages_text) // 4,
            estimated_output_tokens=model_config.max_output_tokens,
        )

        # After a successful call:
        await guard.post_call_record(
            session_id=session_id,
            model_id=model_config.model_id,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            cache_write_tokens=resp.cache_write_tokens,
            cache_read_tokens=resp.cache_read_tokens,
            trace_id=resp.trace_id,
        )
    """

    def __init__(
        self,
        ledger: BudgetLedger,
        policies: Optional[List[BudgetPolicy]] = None,
        alert_callbacks: Optional[List[AlertCallback]] = None,
    ) -> None:
        self._ledger = ledger
        self._policies: List[BudgetPolicy] = [p for p in (policies or []) if p.enabled]
        self._alert_callbacks: List[AlertCallback] = alert_callbacks or []

    # ── Public interface ────────────────────────────────────────────────────

    async def pre_call_check(
        self,
        *,
        session_id: str,
        model_id: str,
        estimated_input_tokens: int = 0,
        estimated_output_tokens: int = 0,
    ) -> None:
        """
        Verify that the projected cost will not breach any active policy.

        Raises:
            BudgetExceededError: when any BLOCK-level policy would be violated.
        """
        if not self._policies:
            return

        projected_cost, _, tier = calculate_cost(
            model_id, estimated_input_tokens, estimated_output_tokens,
        )

        for policy in self._policies:
            snap = self._ledger.snapshot(since_ts=policy.window_start_ts())
            current_spend = snap.total_cost_usd
            prospective_spend = current_spend + projected_cost

            # ── Session sub-limit ───────────────────────────────────────
            if policy.session_limit_usd > 0:
                session_spend = snap.by_session.get(session_id, 0.0) + projected_cost
                if session_spend > policy.session_limit_usd:
                    raise BudgetExceededError(
                        policy_name=f"{policy.name}[session]",
                        limit_usd=policy.session_limit_usd,
                        projected_usd=session_spend,
                        window="session",
                    )

            # ── Tier sub-limit ──────────────────────────────────────────
            if policy.tier_limits and tier.value in policy.tier_limits:
                tier_limit = policy.tier_limits[tier.value]
                tier_spend = snap.by_tier.get(tier.value, 0.0) + projected_cost
                if tier_spend > tier_limit:
                    raise BudgetExceededError(
                        policy_name=f"{policy.name}[tier:{tier.value}]",
                        limit_usd=tier_limit,
                        projected_usd=tier_spend,
                        window=policy.window.value,
                    )

            # ── Evaluate alert thresholds on prospective spend ──────────
            prospective_pct = policy.utilization_pct(prospective_spend)
            for alert in reversed(policy.alerts):
                if prospective_pct >= alert.pct_threshold:
                    await self._fire_alert(policy, alert, snap)
                    if alert.action == ThrottleAction.BLOCK:
                        raise BudgetExceededError(
                            policy_name=policy.name,
                            limit_usd=policy.limit_usd,
                            projected_usd=prospective_spend,
                            window=policy.window.value,
                        )
                    break  # only fire the highest matching threshold

    async def post_call_record(
        self,
        *,
        session_id: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
        trace_id: str = "",
    ) -> None:
        """Record actual token usage after a successful LLM call."""
        await self._ledger.record(
            session_id=session_id,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_write_tokens=cache_write_tokens,
            cache_read_tokens=cache_read_tokens,
            trace_id=trace_id,
        )

        # Re-evaluate alerts on actual spend
        for policy in self._policies:
            snap = self._ledger.snapshot(since_ts=policy.window_start_ts())
            alert = policy.highest_triggered(snap.total_cost_usd)
            if alert:
                await self._fire_alert(policy, alert, snap)

    def current_spend(self, window: BudgetWindow = BudgetWindow.DAILY) -> SpendSnapshot:
        """Convenience: return spend snapshot for a specific window."""
        from ironcore.enterprise.budget.policy import _WINDOW_SECONDS
        secs = _WINDOW_SECONDS[window]
        since = time.time() - secs if secs > 0 else 0.0
        return self._ledger.snapshot(since_ts=since)

    def add_policy(self, policy: BudgetPolicy) -> None:
        if policy.enabled:
            self._policies.append(policy)

    def add_alert_callback(self, cb: AlertCallback) -> None:
        self._alert_callbacks.append(cb)

    @property
    def ledger(self) -> BudgetLedger:
        return self._ledger

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _fire_alert(
        self,
        policy: BudgetPolicy,
        alert: BudgetAlert,
        snap: SpendSnapshot,
    ) -> None:
        pct = policy.utilization_pct(snap.total_cost_usd)
        logger.warning(
            "[BudgetGuard] Alert fired | policy=%s level=%s action=%s spent=$%.4f limit=$%.2f (%.1f%%)",
            policy.name, alert.level.value, alert.action.value,
            snap.total_cost_usd, policy.limit_usd, pct,
        )
        for cb in self._alert_callbacks:
            try:
                await cb(policy, alert, snap)
            except Exception as exc:
                logger.warning("[BudgetGuard] Alert callback error (non-fatal): %s", exc)
