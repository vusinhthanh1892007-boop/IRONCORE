"""
Metrics Collector — Phase 4, Security V3.

In-memory real-time metrics collector for the IronCore security dashboard.
Aggregates counters across all security modules:
  - Prompt Firewall: detections, blocks, quarantines per minute/hour
  - Forensics: session recordings, event rates
  - Guardrail: violations, block rate, top triggered rules
  - General: request rate, session count, active agents

Design:
  - All writes are synchronous (no DB hit) — pure in-memory with deque windows
  - Time-bucketed counters: sliding windows of 1m, 5m, 15m, 1h
  - Thread-safe via asyncio.Lock (single-process only)
  - Persists a snapshot to disk every 30s (env: IRONCORE_METRICS_SNAPSHOT_PATH)
  - MetricsSeries: ordered deque of (timestamp, value) tuples — last 1000 points/series

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_SNAPSHOT_PATH = Path(
    os.environ.get("IRONCORE_METRICS_SNAPSHOT_PATH",
                   str(Path.home() / ".ironcore" / "metrics_snapshot.json"))
)

_MAX_SERIES_POINTS = 1000   # max data points stored per metric series
_WINDOW_SECONDS = {         # sliding windows for rate calculations
    "1m":  60,
    "5m":  300,
    "15m": 900,
    "1h":  3600,
}


# ── Time-bucketed counter ─────────────────────────────────────────────────────

class SlidingCounter:
    """
    Thread-safe sliding window counter backed by a deque of (timestamp, count) tuples.
    Supports multiple window sizes for rate calculations per minute / hour.
    """

    def __init__(self, max_points: int = _MAX_SERIES_POINTS) -> None:
        self._events: Deque[float] = collections.deque(maxlen=max_points * 10)
        self._total: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()

    async def increment(self, n: int = 1) -> None:
        async with self._lock:
            now = time.time()
            for _ in range(n):
                self._events.append(now)
            self._total += n

    def rate(self, window_seconds: int) -> float:
        """Events per second averaged over window_seconds."""
        cutoff = time.time() - window_seconds
        recent = sum(1 for t in self._events if t >= cutoff)
        return recent / window_seconds

    def count_in_window(self, window_seconds: int) -> int:
        cutoff = time.time() - window_seconds
        return sum(1 for t in self._events if t >= cutoff)

    @property
    def total(self) -> int:
        return self._total


# ── Time-series data point storage ────────────────────────────────────────────

class MetricSeries:
    """Ordered deque of (timestamp, value) data points for charting."""

    def __init__(self, name: str, max_points: int = _MAX_SERIES_POINTS) -> None:
        self.name = name
        self._points: Deque[Tuple[float, float]] = collections.deque(maxlen=max_points)

    def record(self, value: float) -> None:
        self._points.append((time.time(), value))

    def to_list(self, limit: int = 200) -> List[Dict[str, float]]:
        """Return last N points as [{"ts": ..., "v": ...}]."""
        points = list(self._points)
        if limit:
            points = points[-limit:]
        return [{"ts": ts, "v": v} for ts, v in points]

    def latest(self) -> Optional[float]:
        if not self._points:
            return None
        return self._points[-1][1]


# ── MetricsCollector ──────────────────────────────────────────────────────────

class MetricsCollector:
    """
    Central in-memory metrics store for all security modules.

    Usage::

        mc = MetricsCollector()
        # From firewall:
        await mc.firewall.detect()
        await mc.firewall.block()
        await mc.firewall.quarantine()
        # From guardrail:
        await mc.guardrail.violation("No financial advice", "block")
        # From forensics:
        await mc.forensics.session_start()

        snapshot = mc.snapshot()   # used by dashboard SSE stream
    """

    def __init__(self) -> None:
        self.firewall   = _FirewallMetrics()
        self.guardrail  = _GuardrailMetrics()
        self.forensics  = _ForensicsMetrics()
        self.system     = _SystemMetrics()
        self._started_at = time.time()
        self._snapshot_path = _SNAPSHOT_PATH

    # ── Snapshot ───────────────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        """
        Return a comprehensive metrics snapshot dict suitable for JSON.
        Used by the SSE dashboard endpoint.
        """
        now = time.time()
        uptime = now - self._started_at

        fw = self.firewall
        gr = self.guardrail
        fo = self.forensics
        sy = self.system

        return {
            "timestamp": now,
            "uptime_seconds": uptime,
            "firewall": {
                "total_detections": fw.detections.total,
                "total_blocks": fw.blocks.total,
                "total_quarantines": fw.quarantines.total,
                "detections_1m": fw.detections.count_in_window(60),
                "detections_5m": fw.detections.count_in_window(300),
                "detections_1h": fw.detections.count_in_window(3600),
                "blocks_1m": fw.blocks.count_in_window(60),
                "quarantines_1h": fw.quarantines.count_in_window(3600),
                "block_rate_1m": round(fw.blocks.rate(60), 4),
                "top_categories": dict(list(fw.category_counts.items())[:5]),
                "detections_series": fw.detection_series.to_list(100),
            },
            "guardrail": {
                "total_violations": gr.violations.total,
                "total_blocks": gr.blocks.total,
                "violations_1m": gr.violations.count_in_window(60),
                "violations_5m": gr.violations.count_in_window(300),
                "block_rate_1m": round(gr.blocks.rate(60), 4),
                "top_rules": dict(list(gr.rule_counts.items())[:5]),
                "violation_series": gr.violation_series.to_list(100),
            },
            "forensics": {
                "total_sessions_recorded": fo.sessions_started.total,
                "total_sessions_ended": fo.sessions_ended.total,
                "active_sessions": max(0, fo.sessions_started.total - fo.sessions_ended.total),
                "total_events_recorded": fo.events_recorded.total,
                "events_1m": fo.events_recorded.count_in_window(60),
            },
            "system": {
                "total_requests": sy.requests.total,
                "requests_1m": sy.requests.count_in_window(60),
                "total_errors": sy.errors.total,
                "errors_1m": sy.errors.count_in_window(60),
                "error_rate_1m": round(sy.errors.rate(60), 4),
                "request_series": sy.request_series.to_list(100),
            },
        }

    async def save_snapshot(self) -> None:
        """Persist metrics snapshot to disk."""
        try:
            self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snap = self.snapshot()
            self._snapshot_path.write_text(
                json.dumps(snap, indent=2), encoding="utf-8"
            )
            logger.debug("[MetricsCollector] Snapshot saved to %s", self._snapshot_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[MetricsCollector] Snapshot save failed: %s", exc)

    def load_snapshot(self) -> Dict[str, Any]:
        """Load last saved snapshot from disk (for UI after restart)."""
        if not self._snapshot_path.exists():
            return {}
        try:
            return json.loads(self._snapshot_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[MetricsCollector] Snapshot load failed: %s", exc)
            return {}


# ── Per-module metrics ─────────────────────────────────────────────────────────

class _FirewallMetrics:
    def __init__(self) -> None:
        self.detections      = SlidingCounter()
        self.blocks          = SlidingCounter()
        self.quarantines     = SlidingCounter()
        self.allows          = SlidingCounter()
        self.category_counts: Dict[str, int] = {}
        self.detection_series = MetricSeries("firewall.detections_per_min")

    async def detect(self, category: str = "unknown") -> None:
        await self.detections.increment()
        self.category_counts[category] = self.category_counts.get(category, 0) + 1
        self.detection_series.record(self.detections.count_in_window(60))

    async def block(self) -> None:
        await self.blocks.increment()

    async def quarantine(self) -> None:
        await self.quarantines.increment()

    async def allow(self) -> None:
        await self.allows.increment()


class _GuardrailMetrics:
    def __init__(self) -> None:
        self.violations      = SlidingCounter()
        self.blocks          = SlidingCounter()
        self.rewrites        = SlidingCounter()
        self.rule_counts: Dict[str, int] = {}
        self.violation_series = MetricSeries("guardrail.violations_per_min")

    async def violation(self, rule_name: str, remedy: str) -> None:
        await self.violations.increment()
        self.rule_counts[rule_name] = self.rule_counts.get(rule_name, 0) + 1
        if remedy == "block":
            await self.blocks.increment()
        elif remedy == "rewrite":
            await self.rewrites.increment()
        self.violation_series.record(self.violations.count_in_window(60))


class _ForensicsMetrics:
    def __init__(self) -> None:
        self.sessions_started = SlidingCounter()
        self.sessions_ended   = SlidingCounter()
        self.events_recorded  = SlidingCounter()

    async def session_start(self) -> None:
        await self.sessions_started.increment()

    async def session_end(self) -> None:
        await self.sessions_ended.increment()

    async def event_recorded(self) -> None:
        await self.events_recorded.increment()


class _SystemMetrics:
    def __init__(self) -> None:
        self.requests       = SlidingCounter()
        self.errors         = SlidingCounter()
        self.request_series = MetricSeries("system.requests_per_min")

    async def request(self) -> None:
        await self.requests.increment()
        self.request_series.record(self.requests.count_in_window(60))

    async def error(self) -> None:
        await self.errors.increment()


# ── Global singleton helper (lazy) ────────────────────────────────────────────

_global_collector: Optional[MetricsCollector] = None


def get_collector() -> MetricsCollector:
    """Return the global MetricsCollector singleton (create if first call)."""
    global _global_collector
    if _global_collector is None:
        _global_collector = MetricsCollector()
    return _global_collector


def set_collector(mc: MetricsCollector) -> None:
    """Inject a custom collector (used in tests)."""
    global _global_collector
    _global_collector = mc
