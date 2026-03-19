"""Budget Policy — configurable spend limits with alert thresholds.

Supports three time windows: hourly, daily, monthly.
Each policy can carry multiple alert thresholds (warn/critical/block)
and specify which throttle action to take at each level.
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Callable, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


class BudgetWindow(str, Enum):
    """Rolling time windows for budget evaluation."""
    HOURLY  = "hourly"   # last 3 600 s
    DAILY   = "daily"    # last 86 400 s
    MONTHLY = "monthly"  # last 2 592 000 s (30 days)
    SESSION = "session"  # unbounded — since ledger creation


_WINDOW_SECONDS: Dict[BudgetWindow, float] = {
    BudgetWindow.HOURLY:  3_600.0,
    BudgetWindow.DAILY:   86_400.0,
    BudgetWindow.MONTHLY: 2_592_000.0,
    BudgetWindow.SESSION: 0.0,   # 0 means "all time" in ledger.snapshot()
}


class AlertLevel(str, Enum):
    """Severity levels for budget alerts."""
    INFO     = "info"
    WARN     = "warn"
    CRITICAL = "critical"
    BLOCK    = "block"   # hard-stop — raises BudgetExceededError


class ThrottleAction(str, Enum):
    """What the guard should do when an alert fires."""
    LOG          = "log"           # record only
    DOWNGRADE    = "downgrade"     # route to cheaper model tier
    REQUIRE_HITL = "require_hitl"  # pause and ask operator approval
    BLOCK        = "block"         # reject the call outright


class BudgetAlert(BaseModel):
    """One alert threshold within a BudgetPolicy."""

    pct_threshold: float = Field(ge=0.0, le=200.0,
        description="Spend as % of policy limit that triggers this alert.")
    level: AlertLevel = AlertLevel.WARN
    action: ThrottleAction = ThrottleAction.LOG
    message: str = ""

    @model_validator(mode="after")
    def block_level_requires_block_action(self) -> "BudgetAlert":
        if self.level == AlertLevel.BLOCK and self.action != ThrottleAction.BLOCK:
            object.__setattr__(self, "action", ThrottleAction.BLOCK)
        return self


class BudgetPolicy(BaseModel):
    """
    A named budget policy: limit + window + ordered alert thresholds.

    Example — $5/day with a warn at 80 %, downgrade at 90 %, hard-block at 100 %:

        BudgetPolicy(
            name="dev-daily",
            limit_usd=5.0,
            window=BudgetWindow.DAILY,
            alerts=[
                BudgetAlert(pct_threshold=80.0, level=AlertLevel.WARN,     action=ThrottleAction.LOG),
                BudgetAlert(pct_threshold=90.0, level=AlertLevel.CRITICAL, action=ThrottleAction.DOWNGRADE),
                BudgetAlert(pct_threshold=100.0, level=AlertLevel.BLOCK,    action=ThrottleAction.BLOCK),
            ],
        )
    """

    name: str
    limit_usd: float = Field(gt=0.0, description="Hard ceiling in US dollars.")
    window: BudgetWindow = BudgetWindow.DAILY
    alerts: List[BudgetAlert] = Field(default_factory=list)
    # Per-session sub-limit (0 = disabled)
    session_limit_usd: float = Field(default=0.0, ge=0.0)
    # Per-tier overrides  e.g. {"premium": 1.0}  ← max $1 on premium models per window
    tier_limits: Dict[str, float] = Field(default_factory=dict)
    # Optional human-readable description
    description: str = ""
    enabled: bool = True

    @model_validator(mode="after")
    def sort_alerts(self) -> "BudgetPolicy":
        object.__setattr__(self, "alerts", sorted(self.alerts, key=lambda a: a.pct_threshold))
        return self

    def window_start_ts(self) -> float:
        secs = _WINDOW_SECONDS[self.window]
        if secs == 0.0:
            return 0.0
        return time.time() - secs

    def utilization_pct(self, spent_usd: float) -> float:
        return (spent_usd / self.limit_usd) * 100.0

    def triggered_alerts(self, spent_usd: float) -> List[BudgetAlert]:
        """Return alerts whose threshold has been crossed (ascending order)."""
        pct = self.utilization_pct(spent_usd)
        return [a for a in self.alerts if pct >= a.pct_threshold]

    def highest_triggered(self, spent_usd: float) -> Optional[BudgetAlert]:
        triggered = self.triggered_alerts(spent_usd)
        return triggered[-1] if triggered else None

    @classmethod
    def default_dev(cls) -> "BudgetPolicy":
        """Sensible defaults for a development environment."""
        return cls(
            name="default-dev",
            limit_usd=10.0,
            window=BudgetWindow.DAILY,
            description="Default: $10/day with warn at 80%, block at 100%",
            alerts=[
                BudgetAlert(pct_threshold=80.0,  level=AlertLevel.WARN,     action=ThrottleAction.LOG),
                BudgetAlert(pct_threshold=95.0,  level=AlertLevel.CRITICAL, action=ThrottleAction.DOWNGRADE),
                BudgetAlert(pct_threshold=100.0, level=AlertLevel.BLOCK,    action=ThrottleAction.BLOCK),
            ],
        )

    @classmethod
    def default_prod(cls) -> "BudgetPolicy":
        """Conservative production defaults."""
        return cls(
            name="default-prod",
            limit_usd=100.0,
            window=BudgetWindow.MONTHLY,
            session_limit_usd=5.0,
            description="$100/month, $5/session, premium tier capped at $20/month",
            tier_limits={"premium": 20.0},
            alerts=[
                BudgetAlert(pct_threshold=50.0,  level=AlertLevel.INFO,     action=ThrottleAction.LOG),
                BudgetAlert(pct_threshold=80.0,  level=AlertLevel.WARN,     action=ThrottleAction.LOG),
                BudgetAlert(pct_threshold=90.0,  level=AlertLevel.CRITICAL, action=ThrottleAction.REQUIRE_HITL),
                BudgetAlert(pct_threshold=100.0, level=AlertLevel.BLOCK,    action=ThrottleAction.BLOCK),
            ],
        )
