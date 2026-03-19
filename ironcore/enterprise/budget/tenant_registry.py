"""Phase 18 — Multi-tenant Budget Isolation.

TenantBudgetRegistry provides per-tenant BudgetLedger + BudgetGuard isolation.
Each tenant gets its own fully independent accounting context, lazily created on
first access.  No state is shared between tenants.

Env vars:
    IRONCORE_MULTITENANCY_ENABLED=true
    IRONCORE_DEFAULT_TENANT_DAILY_LIMIT_USD=10.0
    IRONCORE_DEFAULT_TENANT_SESSION_LIMIT_USD=1.0
    IRONCORE_TENANT_MAX_ACTIVE=1000
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from ironcore.enterprise.budget.guard import AlertCallback, BudgetGuard
from ironcore.enterprise.budget.ledger import BudgetLedger, SpendSnapshot
from ironcore.enterprise.budget.policy import (
    AlertLevel,
    BudgetAlert,
    BudgetPolicy,
    BudgetWindow,
    ThrottleAction,
)

logger = logging.getLogger(__name__)

# ── Config from env ──────────────────────────────────────────────────────────
_ENABLED = os.environ.get("IRONCORE_MULTITENANCY_ENABLED", "true").lower() != "false"
_DEFAULT_DAILY_LIMIT = float(
    os.environ.get("IRONCORE_DEFAULT_TENANT_DAILY_LIMIT_USD", "10.0")
)
_DEFAULT_SESSION_LIMIT = float(
    os.environ.get("IRONCORE_DEFAULT_TENANT_SESSION_LIMIT_USD", "1.0")
)
_MAX_ACTIVE = int(os.environ.get("IRONCORE_TENANT_MAX_ACTIVE", "1000"))


# ── Default policy factory ────────────────────────────────────────────────────

def _default_tenant_policy() -> BudgetPolicy:
    """Default per-tenant policy: daily limit with warn and block thresholds."""
    return BudgetPolicy(
        name="tenant-default",
        limit_usd=_DEFAULT_DAILY_LIMIT,
        window=BudgetWindow.DAILY,
        session_limit_usd=_DEFAULT_SESSION_LIMIT,
        description="Auto-created default tenant policy",
        alerts=[
            BudgetAlert(
                pct_threshold=80.0,
                level=AlertLevel.WARN,
                action=ThrottleAction.LOG,
            ),
            BudgetAlert(
                pct_threshold=100.0,
                level=AlertLevel.BLOCK,
                action=ThrottleAction.BLOCK,
            ),
        ],
    )


# ── Data model ───────────────────────────────────────────────────────────────

class TenantBudgetContext(BaseModel):
    """All budget state for one tenant — completely isolated from other tenants."""

    model_config = {"arbitrary_types_allowed": True}

    tenant_id: str
    ledger: BudgetLedger
    guard: BudgetGuard
    policy: BudgetPolicy
    created_at: float = Field(default_factory=time.time)
    last_activity: float = Field(default_factory=time.time)


# ── Registry ─────────────────────────────────────────────────────────────────

class TenantBudgetRegistry:
    """
    Lazy-init per-tenant BudgetLedger + BudgetGuard.
    Thread-safe with asyncio.Lock per tenant.

    Usage::

        registry = TenantBudgetRegistry()
        guard = await registry.get_guard("tenant-abc")
        await guard.pre_call_check(...)
    """

    def __init__(
        self,
        default_policy_factory: Callable[[], BudgetPolicy] = _default_tenant_policy,
        alert_callbacks: Optional[List[AlertCallback]] = None,
        max_active: int = _MAX_ACTIVE,
    ) -> None:
        self._policy_factory = default_policy_factory
        self._alert_callbacks: List[AlertCallback] = alert_callbacks or []
        self._max_active = max_active
        # Main store: tenant_id → TenantBudgetContext
        self._contexts: Dict[str, TenantBudgetContext] = {}
        # Per-tenant locks for safe lazy init under concurrency
        self._init_locks: Dict[str, asyncio.Lock] = {}
        # Global lock only for creating new per-tenant locks
        self._registry_lock = asyncio.Lock()

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _get_or_create_lock(self, tenant_id: str) -> asyncio.Lock:
        """Return the per-tenant asyncio.Lock, creating it if necessary."""
        if tenant_id not in self._init_locks:
            async with self._registry_lock:
                if tenant_id not in self._init_locks:
                    self._init_locks[tenant_id] = asyncio.Lock()
        return self._init_locks[tenant_id]

    async def _ensure_context(self, tenant_id: str) -> TenantBudgetContext:
        """Lazy-init: create TenantBudgetContext on first access for tenant_id."""
        if tenant_id in self._contexts:
            ctx = self._contexts[tenant_id]
            ctx.last_activity = time.time()
            return ctx

        lock = await self._get_or_create_lock(tenant_id)
        async with lock:
            # Double-checked locking
            if tenant_id in self._contexts:
                ctx = self._contexts[tenant_id]
                ctx.last_activity = time.time()
                return ctx

            if len(self._contexts) >= self._max_active:
                raise RuntimeError(
                    f"[TenantBudgetRegistry] Max active tenants ({self._max_active}) reached."
                )

            policy = self._policy_factory()
            ledger = BudgetLedger()
            guard = BudgetGuard(
                ledger=ledger,
                policies=[policy],
                alert_callbacks=list(self._alert_callbacks),
            )
            ctx = TenantBudgetContext(
                tenant_id=tenant_id,
                ledger=ledger,
                guard=guard,
                policy=policy,
            )
            self._contexts[tenant_id] = ctx
            logger.info(
                "[TenantBudgetRegistry] New tenant context created | tenant=%s | "
                "limit=$%.2f | window=%s",
                tenant_id, policy.limit_usd, policy.window.value,
            )
            return ctx

    # ── Public interface ──────────────────────────────────────────────────────

    async def get_guard(self, tenant_id: str) -> BudgetGuard:
        """Return the BudgetGuard for tenant_id, lazy-creating context if needed."""
        ctx = await self._ensure_context(tenant_id)
        return ctx.guard

    async def get_ledger(self, tenant_id: str) -> BudgetLedger:
        """Return the BudgetLedger for tenant_id."""
        ctx = await self._ensure_context(tenant_id)
        return ctx.ledger

    async def get_snapshot(
        self,
        tenant_id: str,
        window: BudgetWindow = BudgetWindow.DAILY,
    ) -> SpendSnapshot:
        """Return a spend snapshot for the given tenant and time window."""
        ctx = await self._ensure_context(tenant_id)
        return ctx.guard.current_spend(window)

    async def update_policy(self, tenant_id: str, policy: BudgetPolicy) -> None:
        """Replace the active policy for tenant_id with a new one."""
        ctx = await self._ensure_context(tenant_id)
        lock = await self._get_or_create_lock(tenant_id)
        async with lock:
            new_guard = BudgetGuard(
                ledger=ctx.ledger,
                policies=[policy],
                alert_callbacks=list(self._alert_callbacks),
            )
            new_ctx = TenantBudgetContext(
                tenant_id=tenant_id,
                ledger=ctx.ledger,
                guard=new_guard,
                policy=policy,
                created_at=ctx.created_at,
            )
            self._contexts[tenant_id] = new_ctx
            logger.info(
                "[TenantBudgetRegistry] Policy updated | tenant=%s | "
                "new_limit=$%.2f | window=%s",
                tenant_id, policy.limit_usd, policy.window.value,
            )

    async def list_tenants(self) -> List[str]:
        """Return all tenant_ids currently tracked in memory."""
        return list(self._contexts.keys())

    async def reset_tenant(self, tenant_id: str) -> None:
        """System admin: reset ledger + policy to defaults for tenant_id."""
        lock = await self._get_or_create_lock(tenant_id)
        async with lock:
            policy = self._policy_factory()
            ledger = BudgetLedger()
            guard = BudgetGuard(
                ledger=ledger,
                policies=[policy],
                alert_callbacks=list(self._alert_callbacks),
            )
            created_at = (
                self._contexts[tenant_id].created_at
                if tenant_id in self._contexts
                else time.time()
            )
            self._contexts[tenant_id] = TenantBudgetContext(
                tenant_id=tenant_id,
                ledger=ledger,
                guard=guard,
                policy=policy,
                created_at=created_at,
            )
            logger.info(
                "[TenantBudgetRegistry] Tenant reset | tenant=%s", tenant_id
            )

    def tenant_count(self) -> int:
        """Number of tenants currently in the registry."""
        return len(self._contexts)


# ── Access-control helper (no HTTP dependency) ────────────────────────────────

class TenantAccessDeniedError(PermissionError):
    """Raised when a tenant admin tries to access another tenant's data."""

    def __init__(self, target_tenant: str) -> None:
        super().__init__(
            f"Access denied: you may not access tenant '{target_tenant}'."
        )
        self.target_tenant = target_tenant


def check_tenant_access(
    caller_tenant: Optional[str],
    target_tenant: str,
) -> None:
    """Verify caller has access to target_tenant.

    Args:
        caller_tenant: The requesting tenant ID, or ``None`` for system admin.
        target_tenant: The tenant whose resources are being accessed.

    Raises:
        TenantAccessDeniedError: if ``caller_tenant`` is set and differs from
            ``target_tenant``.
    """
    if caller_tenant is not None and caller_tenant != target_tenant:
        raise TenantAccessDeniedError(target_tenant)
