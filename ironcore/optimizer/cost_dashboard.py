"""
IronCore Optimizer — Phase 4B: Cost Dashboard
==============================================
Claude 4.6 "The Optimizer" — IronCore V2

Aggregate metrics từ toàn bộ optimizer stack:
  - SemanticCache (Phase 1): cache hit/miss counts
  - PromptKVCacheManager (Phase 2): Anthropic KV-cache token savings
  - TokenCompressor (Phase 3): compression tokens saved
  - LLMBridge CostTracker: actual API costs

Output:
  - SessionCostReport: per-session summary cho dashboard
  - MetricPoint time-series: data cho charts (cost/minute)
  - get_global_report: aggregate across tất cả sessions

GPT-5.4 (UI Designer) sẽ consume:
  - get_session_report(session_id) → render per-session widget
  - get_time_series(metric="cost") → render line chart
  - get_global_report(hours=24) → render global stats table

Author: The Optimizer (Claude 4.6) — IronCore V2
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────────────────────────────────────


class MetricPoint(BaseModel):
    """
    Một điểm dữ liệu cho time-series chart.
    Dùng cho cost/minute, cache hit rate/minute, etc.
    """

    timestamp: float                # Unix timestamp
    value: float                    # Giá trị metric tại thời điểm đó
    label: str = ""                 # Label cho UI (e.g., "2024-03-11 13:00")


class SessionCostReport(BaseModel):
    """
    Báo cáo chi phí đầy đủ cho một session.
    Được GPT-5.4 consume để render dashboard widgets.
    """

    session_id: str
    start_time: float
    duration_seconds: float

    # ── API Call Stats ─────────────────────────────────────────────────
    total_api_calls: int = 0
    semantic_cache_hits: int = 0
    semantic_cache_hit_rate: float = 0.0
    kv_cache_hit_rate: float = 0.0       # Từ Anthropic usage.cache_read_input_tokens

    # ── Token Stats ────────────────────────────────────────────────────
    tokens_sent: int = 0
    tokens_received: int = 0
    tokens_saved_by_cache: int = 0       # Ước tính từ SemanticCache hits
    tokens_saved_by_kv_cache: int = 0    # cache_read_input_tokens * (1-0.10)
    tokens_saved_by_compression: int = 0 # TokenCompressor.stats.total_tokens_saved

    # ── Cost Stats ($USD) ──────────────────────────────────────────────
    total_cost_usd: float = 0.0
    estimated_without_optimizer_usd: float = 0.0

    @property
    def savings_usd(self) -> float:
        return max(
            0.0,
            round(self.estimated_without_optimizer_usd - self.total_cost_usd, 6),
        )

    @property
    def savings_pct(self) -> float:
        if self.estimated_without_optimizer_usd <= 0:
            return 0.0
        return round(
            self.savings_usd / self.estimated_without_optimizer_usd * 100, 2
        )

    # ── Time-series ────────────────────────────────────────────────────
    time_series: List[MetricPoint] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Internal: Per-session raw data bucket
# ──────────────────────────────────────────────────────────────────────────────


class _SessionBucket:
    """Raw data accumulator per session. Thread/asyncio safe via lock."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.start_time: float = time.time()
        self.lock = asyncio.Lock()

        # Counters
        self.total_api_calls: int = 0
        self.cache_hits: int = 0            # SemanticCache hits
        self.tokens_sent: int = 0
        self.tokens_received: int = 0
        self.total_cost_usd: float = 0.0

        # KV-cache from Anthropic
        self.kv_cache_reads: int = 0        # calls with cache_read > 0
        self.kv_cache_read_tokens: int = 0  # total cache_read_input_tokens

        # Compression savings
        self.tokens_saved_by_compression: int = 0

        # Time-series: list of (ts, cost_usd) tuples
        self.cost_timeline: List[tuple] = []  # (timestamp, incremental_cost_usd)

    async def record_call(
        self,
        tokens_used: int,
        cost_usd: float,
        model_id: str,
        cache_hit: bool,
        tokens_received: int = 0,
        kv_cache_read_tokens: int = 0,
    ) -> None:
        async with self.lock:
            self.total_api_calls += 1
            if cache_hit:
                self.cache_hits += 1
            self.tokens_sent += tokens_used
            self.tokens_received += tokens_received
            self.total_cost_usd += cost_usd
            if kv_cache_read_tokens > 0:
                self.kv_cache_reads += 1
                self.kv_cache_read_tokens += kv_cache_read_tokens
            self.cost_timeline.append((time.time(), cost_usd))


# ──────────────────────────────────────────────────────────────────────────────
# CostDashboard — Public Interface
# ──────────────────────────────────────────────────────────────────────────────


class CostDashboard:
    """
    Central metrics aggregator cho IronCore Optimizer.

    Tổng hợp cost data từ:
      - LLMBridge API calls (cost_usd per call)
      - SemanticCache (cache hits)
      - PromptKVCacheManager (KV-cache savings)
      - TokenCompressor (compression savings)

    Provides time-series data cho GPT-5.4 Dashboard UI.

    Usage::
        dashboard = CostDashboard()

        # Trong LLMBridge.call_llm sau mỗi successful call:
        await dashboard.record_api_call(
            session_id=session_id,
            tokens_used=input_tokens,
            cost_usd=cost,
            model_id=model_config.model_id,
            cache_hit=False,
            tokens_received=output_tokens,
        )

        # GPT-5.4 query:
        report = await dashboard.get_session_report(session_id)
    """

    # Giá per 1K input tokens (USD) — rough estimates
    _MODEL_COSTS: Dict[str, float] = {
        "claude-sonnet": 0.003,
        "claude-haiku": 0.00025,
        "claude-opus": 0.015,
        "gpt-4o": 0.0025,
        "gpt-4o-mini": 0.00015,
        "gemini": 0.00125,
    }
    _DEFAULT_COST_PER_1K = 0.002  # Conservative fallback

    def __init__(self) -> None:
        self._sessions: Dict[str, _SessionBucket] = {}
        self._global_lock = asyncio.Lock()
        logger.info("[CostDashboard] Initialized.")

    # ── Core Recording API ────────────────────────────────────────────────────

    async def record_api_call(
        self,
        session_id: str,
        tokens_used: int,
        cost_usd: float,
        model_id: str,
        cache_hit: bool,
        tokens_received: int = 0,
        kv_cache_read_tokens: int = 0,
    ) -> None:
        """
        Ghi nhận một LLM API call.

        Args:
            session_id:            Active session ID.
            tokens_used:           Input tokens consumed.
            cost_usd:              Actual cost accrued.
            model_id:              LiteLLM model string.
            cache_hit:             True nếu kết quả từ SemanticCache.
            tokens_received:       Output tokens.
            kv_cache_read_tokens:  Anthropic cache_read_input_tokens nếu có.
        """
        bucket = await self._get_or_create_bucket(session_id)
        await bucket.record_call(
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            model_id=model_id,
            cache_hit=cache_hit,
            tokens_received=tokens_received,
            kv_cache_read_tokens=kv_cache_read_tokens,
        )
        logger.debug(
            "[CostDashboard] Recorded | session=%s model=%s tokens=%d cost=$%.6f cache=%s",
            session_id[:8],
            model_id,
            tokens_used,
            cost_usd,
            cache_hit,
        )

    async def record_compression_savings(
        self,
        session_id: str,
        tokens_saved: int,
    ) -> None:
        """
        Ghi nhận token savings từ TokenCompressor.

        Args:
            session_id:   Active session.
            tokens_saved: Number of tokens saved by compression.
        """
        bucket = await self._get_or_create_bucket(session_id)
        async with bucket.lock:
            bucket.tokens_saved_by_compression += tokens_saved

    # ── Report Generation ─────────────────────────────────────────────────────

    async def get_session_report(self, session_id: str) -> SessionCostReport:
        """
        Tạo SessionCostReport cho một session cụ thể.

        Args:
            session_id: Session ID cần report.

        Returns:
            SessionCostReport với đầy đủ metrics.
        """
        bucket = await self._get_or_create_bucket(session_id)
        async with bucket.lock:
            return self._build_report(bucket)

    async def get_global_report(self, hours: int = 24) -> SessionCostReport:
        """
        Tổng hợp report cho tất cả sessions trong N giờ qua.

        Args:
            hours: Cửa sổ thời gian (mặc định 24h).

        Returns:
            Aggregated SessionCostReport.
        """
        cutoff = time.time() - hours * 3600
        async with self._global_lock:
            recent_sessions = [
                b for b in self._sessions.values()
                if b.start_time >= cutoff
            ]

        if not recent_sessions:
            return SessionCostReport(
                session_id="global",
                start_time=time.time(),
                duration_seconds=0.0,
            )

        # Aggregate
        agg = _SessionBucket("global")
        agg.start_time = min(b.start_time for b in recent_sessions)
        for b in recent_sessions:
            async with b.lock:
                agg.total_api_calls += b.total_api_calls
                agg.cache_hits += b.cache_hits
                agg.tokens_sent += b.tokens_sent
                agg.tokens_received += b.tokens_received
                agg.total_cost_usd += b.total_cost_usd
                agg.kv_cache_reads += b.kv_cache_reads
                agg.kv_cache_read_tokens += b.kv_cache_read_tokens
                agg.tokens_saved_by_compression += b.tokens_saved_by_compression
                agg.cost_timeline.extend(b.cost_timeline)

        return self._build_report(agg)

    async def get_time_series(
        self,
        metric: str = "cost",
        hours: int = 24,
        bucket_minutes: int = 5,
    ) -> List[MetricPoint]:
        """
        Trả về time-series data cho một metric.

        Args:
            metric:         "cost" | "cache_hit_rate" | "tokens_saved" | "api_calls"
            hours:          Window (giờ).
            bucket_minutes: Mỗi điểm đại diện cho bao nhiêu phút.

        Returns:
            List[MetricPoint] theo chronological order.
        """
        cutoff = time.time() - hours * 3600
        bucket_secs = bucket_minutes * 60

        # Collect all events
        all_calls: List[tuple] = []  # (timestamp, cost_usd, cache_hit)
        async with self._global_lock:
            sessions_copy = list(self._sessions.values())

        for b in sessions_copy:
            async with b.lock:
                for ts, cost in b.cost_timeline:
                    if ts >= cutoff:
                        all_calls.append((ts, cost, b.cache_hits / max(b.total_api_calls, 1)))

        if not all_calls:
            return []

        # Group by time bucket
        min_ts = min(t[0] for t in all_calls)
        max_ts = max(t[0] for t in all_calls)
        time_range = max(max_ts - min_ts, bucket_secs)
        n_buckets = max(1, int(time_range / bucket_secs) + 1)

        buckets: Dict[int, List[float]] = defaultdict(list)
        for ts, cost, _ in all_calls:
            bucket_idx = int((ts - min_ts) / bucket_secs)
            if metric == "cost":
                buckets[bucket_idx].append(cost)
            elif metric == "api_calls":
                buckets[bucket_idx].append(1.0)

        import datetime
        points: List[MetricPoint] = []
        for i in range(n_buckets):
            ts = min_ts + i * bucket_secs
            values = buckets.get(i, [])
            value = sum(values) if values else 0.0
            dt = datetime.datetime.fromtimestamp(ts)
            points.append(MetricPoint(
                timestamp=ts,
                value=round(value, 6),
                label=dt.strftime("%H:%M"),
            ))

        return points

    # ── Private Helpers ───────────────────────────────────────────────────────

    async def _get_or_create_bucket(self, session_id: str) -> _SessionBucket:
        async with self._global_lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = _SessionBucket(session_id)
            return self._sessions[session_id]

    def _build_report(self, bucket: _SessionBucket) -> SessionCostReport:
        """Convert _SessionBucket to SessionCostReport."""
        now = time.time()
        duration = now - bucket.start_time
        total_calls = bucket.total_api_calls

        # SemanticCache hit rate
        sem_hit_rate = (
            bucket.cache_hits / total_calls if total_calls > 0 else 0.0
        )

        # KV-cache hit rate
        kv_hit_rate = (
            bucket.kv_cache_reads / total_calls if total_calls > 0 else 0.0
        )

        # Estimated tokens saved by SemanticCache
        # Giả định mỗi cache hit tiết kiệm trung bình 500 input tokens
        _AVG_TOKENS_PER_CALL = 500
        tokens_saved_cache = bucket.cache_hits * _AVG_TOKENS_PER_CALL

        # Tokens saved by KV-cache = 90% of cache_read tokens (10% còn lại là actual cost)
        tokens_saved_kv = int(bucket.kv_cache_read_tokens * 0.90)

        # Estimated cost WITHOUT optimizer
        # = total tokens_sent * model_cost_per_1k / 1000 (if no caching)
        total_tokens_equiv = bucket.tokens_sent + tokens_saved_cache
        _avg_cost_per_1k = self._DEFAULT_COST_PER_1K
        cost_without_optimizer = (total_tokens_equiv / 1_000) * _avg_cost_per_1k

        # Time-series từ cost_timeline
        ts_points = [
            MetricPoint(
                timestamp=ts,
                value=round(cost, 6),
                label="",
            )
            for ts, cost in sorted(bucket.cost_timeline)
        ]

        return SessionCostReport(
            session_id=bucket.session_id,
            start_time=bucket.start_time,
            duration_seconds=round(duration, 2),
            total_api_calls=total_calls,
            semantic_cache_hits=bucket.cache_hits,
            semantic_cache_hit_rate=round(sem_hit_rate, 4),
            kv_cache_hit_rate=round(kv_hit_rate, 4),
            tokens_sent=bucket.tokens_sent,
            tokens_received=bucket.tokens_received,
            tokens_saved_by_cache=tokens_saved_cache,
            tokens_saved_by_kv_cache=tokens_saved_kv,
            tokens_saved_by_compression=bucket.tokens_saved_by_compression,
            total_cost_usd=round(bucket.total_cost_usd, 6),
            estimated_without_optimizer_usd=round(cost_without_optimizer, 6),
            time_series=ts_points,
        )
