"""Budget Ledger — real-time token/cost accounting with tamper-evident chaining.

Key properties:
- Thread-safe via asyncio.Lock (no race conditions under concurrent LLM calls)
- Append-only LedgerEntry list — entries are never deleted
- SpendSnapshot cached and invalidated on append
- Compatible with both real LiteLLM responses and test stubs
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import defaultdict
from enum import Enum
from typing import Callable, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    """Cost tiers matching IronCore's LLM routing tiers."""
    NANO = "nano"        # local / free models (0 cost)
    MINI = "mini"        # Haiku, GPT-4o-mini
    STANDARD = "standard"  # Sonnet, GPT-4o
    PREMIUM = "premium"  # Opus, GPT-4 Turbo, o1
    UNKNOWN = "unknown"  # fallback when model not in price table


# Public price table (USD per 1 M tokens, input/output).
# Updated 2026-03; add new models by extending this dict.
MODEL_PRICE_TABLE: Dict[str, Dict[str, float]] = {
    # Anthropic
    "claude-haiku":           {"input": 0.25,   "output": 1.25,   "tier": ModelTier.MINI},
    "claude-3-haiku":         {"input": 0.25,   "output": 1.25,   "tier": ModelTier.MINI},
    "claude-sonnet":          {"input": 3.00,   "output": 15.00,  "tier": ModelTier.STANDARD},
    "claude-3-sonnet":        {"input": 3.00,   "output": 15.00,  "tier": ModelTier.STANDARD},
    "claude-3-5-sonnet":      {"input": 3.00,   "output": 15.00,  "tier": ModelTier.STANDARD},
    "claude-3-7-sonnet":      {"input": 3.00,   "output": 15.00,  "tier": ModelTier.STANDARD},
    "claude-opus":            {"input": 15.00,  "output": 75.00,  "tier": ModelTier.PREMIUM},
    "claude-3-opus":          {"input": 15.00,  "output": 75.00,  "tier": ModelTier.PREMIUM},
    # OpenAI
    "gpt-4o-mini":            {"input": 0.15,   "output": 0.60,   "tier": ModelTier.MINI},
    "gpt-4o":                 {"input": 2.50,   "output": 10.00,  "tier": ModelTier.STANDARD},
    "gpt-4-turbo":            {"input": 10.00,  "output": 30.00,  "tier": ModelTier.PREMIUM},
    "gpt-4.5":                {"input": 75.00,  "output": 150.00, "tier": ModelTier.PREMIUM},
    "o1":                     {"input": 15.00,  "output": 60.00,  "tier": ModelTier.PREMIUM},
    "o3-mini":                {"input": 1.10,   "output": 4.40,   "tier": ModelTier.MINI},
    # Google
    "gemini-1.5-pro":         {"input": 3.50,   "output": 10.50,  "tier": ModelTier.STANDARD},
    "gemini-2.0-flash":       {"input": 0.10,   "output": 0.40,   "tier": ModelTier.MINI},
    "gemini-2.5-pro":         {"input": 1.25,   "output": 10.00,  "tier": ModelTier.STANDARD},
    # Local / free
    "ollama/llama3":          {"input": 0.00,   "output": 0.00,   "tier": ModelTier.NANO},
    "ollama/mistral":         {"input": 0.00,   "output": 0.00,   "tier": ModelTier.NANO},
}


class BudgetExceededError(Exception):
    """Raised when a proposed LLM call would breach an active budget policy."""

    def __init__(self, policy_name: str, limit_usd: float, projected_usd: float, window: str) -> None:
        self.policy_name = policy_name
        self.limit_usd = limit_usd
        self.projected_usd = projected_usd
        self.window = window
        super().__init__(
            f"[BudgetGuard] Budget '{policy_name}' exceeded: "
            f"projected ${projected_usd:.4f} > limit ${limit_usd:.4f} ({window})"
        )


class LedgerEntry(BaseModel):
    """Immutable record of a single LLM call's cost."""

    model_config = {"frozen": True}

    entry_id: str
    timestamp: float = Field(default_factory=time.time)
    session_id: str
    model_id: str
    tier: ModelTier = ModelTier.UNKNOWN
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    # Anthropic cache-read is billed at 10% of input rate
    cost_usd: float = Field(ge=0.0)
    trace_id: str = Field(default="")
    prev_hash: str = Field(default="")
    entry_hash: str = Field(default="")

    @classmethod
    def compute_hash(cls, entry_id: str, timestamp: float, session_id: str,
                     model_id: str, input_tokens: int, output_tokens: int,
                     cost_usd: float, prev_hash: str) -> str:
        payload = json.dumps({
            "entry_id": entry_id,
            "timestamp": round(timestamp, 6),
            "session_id": session_id,
            "model_id": model_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 8),
            "prev_hash": prev_hash,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


class SpendSnapshot(BaseModel):
    """Point-in-time summary of accumulated spend."""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    total_cache_write_tokens: int = 0
    total_cache_read_tokens: int = 0
    cache_savings_usd: float = 0.0
    entry_count: int = 0
    by_model: Dict[str, float] = Field(default_factory=dict)
    by_tier: Dict[str, float] = Field(default_factory=dict)
    by_session: Dict[str, float] = Field(default_factory=dict)
    window_start_ts: float = 0.0
    window_end_ts: float = Field(default_factory=time.time)


def _lookup_price(model_id: str) -> Dict[str, float]:
    """Return price config for model_id using prefix matching."""
    lower = model_id.lower()
    # exact match first
    if lower in MODEL_PRICE_TABLE:
        return MODEL_PRICE_TABLE[lower]
    # longest prefix match
    best: Optional[str] = None
    for key in MODEL_PRICE_TABLE:
        if lower.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    if best:
        return MODEL_PRICE_TABLE[best]
    return {"input": 0.0, "output": 0.0, "tier": ModelTier.UNKNOWN}


def calculate_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> tuple[float, float, ModelTier]:
    """
    Compute (cost_usd, cache_savings_usd, tier) for a single LLM call.

    Anthropic cache economics:
    - cache_write_tokens: billed at 1.25× input rate (creating a new cache block)
    - cache_read_tokens:  billed at 0.10× input rate (reading an existing block)
    Standard input tokens are those not covered by cache.
    """
    price = _lookup_price(model_id)
    input_rate = price["input"] / 1_000_000   # per-token
    output_rate = price["output"] / 1_000_000  # per-token
    tier = price["tier"]

    # Cost without cache (baseline for savings calculation)
    full_input_cost = (input_tokens + cache_write_tokens + cache_read_tokens) * input_rate

    # Actual billed cost
    actual_cost = (
        input_tokens * input_rate
        + cache_write_tokens * (input_rate * 1.25)   # 25% surcharge to write
        + cache_read_tokens  * (input_rate * 0.10)   # 90% discount to read
        + output_tokens * output_rate
    )

    # Baseline cost if cached tokens were billed as standard input tokens
    baseline_cache_tokens_cost = (cache_write_tokens + cache_read_tokens) * input_rate
    actual_cache_tokens_cost = (
        cache_write_tokens * (input_rate * 1.25)
        + cache_read_tokens  * (input_rate * 0.10)
    )
    cache_savings = max(0.0, baseline_cache_tokens_cost - actual_cache_tokens_cost)

    return actual_cost, cache_savings, tier



class BudgetLedger:
    """
    Append-only cost ledger for all LLM calls.

    Thread-safe via asyncio.Lock.
    Provides both full-history and windowed spend queries.
    """

    def __init__(self) -> None:
        self._entries: List[LedgerEntry] = []
        self._lock = asyncio.Lock()
        self._snapshot_cache: Optional[SpendSnapshot] = None
        self._snapshot_ts: float = 0.0

    async def record(
        self,
        *,
        session_id: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
        trace_id: str = "",
        entry_id: Optional[str] = None,
    ) -> LedgerEntry:
        """Append a new entry; returns the finalized LedgerEntry."""
        import uuid as _uuid

        cost_usd, _, tier = calculate_cost(
            model_id, input_tokens, output_tokens,
            cache_write_tokens, cache_read_tokens,
        )

        async with self._lock:
            prev_hash = self._entries[-1].entry_hash if self._entries else ""
            _entry_id = entry_id or str(_uuid.uuid4())
            ts = time.time()
            h = LedgerEntry.compute_hash(
                _entry_id, ts, session_id, model_id,
                input_tokens, output_tokens, cost_usd, prev_hash,
            )
            entry = LedgerEntry(
                entry_id=_entry_id,
                timestamp=ts,
                session_id=session_id,
                model_id=model_id,
                tier=tier,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_write_tokens=cache_write_tokens,
                cache_read_tokens=cache_read_tokens,
                cost_usd=cost_usd,
                trace_id=trace_id,
                prev_hash=prev_hash,
                entry_hash=h,
            )
            self._entries.append(entry)
            self._snapshot_cache = None  # invalidate
            logger.debug(
                "[BudgetLedger] record | session=%s model=%s cost=$%.6f total_entries=%d",
                session_id, model_id, cost_usd, len(self._entries),
            )
            return entry

    def snapshot(self, since_ts: float = 0.0) -> SpendSnapshot:
        """Return a SpendSnapshot of entries (optionally filtered by window start)."""
        now = time.time()
        # Use cache only if no window filter and cache is fresh (< 0.1s)
        if since_ts == 0.0 and self._snapshot_cache and (now - self._snapshot_ts) < 0.1:
            return self._snapshot_cache

        entries = [e for e in self._entries if e.timestamp >= since_ts]

        by_model: Dict[str, float] = defaultdict(float)
        by_tier: Dict[str, float] = defaultdict(float)
        by_session: Dict[str, float] = defaultdict(float)
        total_in = total_out = total_cw = total_cr = 0
        total_cost = total_savings = 0.0

        for e in entries:
            _, savings, _ = calculate_cost(
                e.model_id, e.input_tokens, e.output_tokens,
                e.cache_write_tokens, e.cache_read_tokens,
            )
            by_model[e.model_id] += e.cost_usd
            by_tier[e.tier.value] += e.cost_usd
            by_session[e.session_id] += e.cost_usd
            total_in  += e.input_tokens
            total_out += e.output_tokens
            total_cw  += e.cache_write_tokens
            total_cr  += e.cache_read_tokens
            total_cost += e.cost_usd
            total_savings += savings

        snap = SpendSnapshot(
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_cache_write_tokens=total_cw,
            total_cache_read_tokens=total_cr,
            total_cost_usd=total_cost,
            cache_savings_usd=total_savings,
            entry_count=len(entries),
            by_model=dict(by_model),
            by_tier=dict(by_tier),
            by_session=dict(by_session),
            window_start_ts=since_ts,
            window_end_ts=now,
        )

        if since_ts == 0.0:
            self._snapshot_cache = snap
            self._snapshot_ts = now
        return snap

    def projected_cost(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float:
        """Estimate cost (USD) for a hypothetical call without recording it."""
        cost, _, _ = calculate_cost(
            model_id, input_tokens, output_tokens,
            cache_write_tokens, cache_read_tokens,
        )
        return cost

    def verify_chain(self) -> bool:
        """Verify tamper-evidence: recompute all hashes and check chain integrity."""
        prev = ""
        for entry in self._entries:
            expected = LedgerEntry.compute_hash(
                entry.entry_id, entry.timestamp, entry.session_id,
                entry.model_id, entry.input_tokens, entry.output_tokens,
                entry.cost_usd, prev,
            )
            if entry.entry_hash != expected:
                logger.warning("[BudgetLedger] Chain integrity failure at entry %s", entry.entry_id)
                return False
            prev = entry.entry_hash
        return True

    @property
    def entries(self) -> List[LedgerEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
