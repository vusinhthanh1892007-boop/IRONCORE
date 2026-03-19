"""SIEMStreamer — reliable, ring-buffered SIEM event streamer.

Architecture
------------
* ``emit(entry)`` is **non-blocking**: the event is placed on an internal
  ``asyncio.Queue`` (ring buffer, max ``buffer_size`` items) and returns
  immediately so the caller's hot path is never delayed.
* A background ``_flush_loop`` task drains the queue every ``flush_interval``
  seconds, formats each entry via ``CEFFormatter``, optionally masks PII with
  ``DLPEngine``, and delivers batches to all configured transports in parallel.
* **Retry policy**: 3 attempts per transport with exponential backoff
  (1 s → 2 s → 4 s).  Permanent failures write a failsafe JSONL file.
* **Buffer overflow**: when the internal queue is full (ring buffer saturated)
  the oldest pending event is silently dropped and an overflow counter is
  incremented — the caller is never blocked.
* Multiple transports are supported (fan-out): the same batch is delivered to
  Splunk, Syslog, and Datadog simultaneously.

Requires ``IRONCORE_EDITION=enterprise``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, List, Optional

from ironcore.edition import check_enterprise
from ironcore.enterprise.siem.cef_formatter import CEFFormatter
from ironcore.enterprise.siem.transports import BaseSIEMTransport
from ironcore.monitoring.schemas import AuditLogEntry

logger = logging.getLogger(__name__)

_MAX_RETRY = 3
_RETRY_BASE = 1.0  # seconds; backoff = base * 2^attempt


# ══════════════════════════════════════════════════════════════════════════════
#  SIEMStreamer
# ══════════════════════════════════════════════════════════════════════════════

class SIEMStreamer:
    """Reliable, ring-buffered SIEM event streamer with DLP masking.

    Requires ``IRONCORE_EDITION=enterprise``.

    Parameters
    ----------
    transports:
        One or more ``BaseSIEMTransport`` instances.  The same batch of events
        is sent to *all* transports (fan-out).
    formatter:
        ``CEFFormatter`` used to convert ``AuditLogEntry`` objects to CEF strings.
    dlp_engine:
        Optional ``DLPEngine``.  When provided, each CEF line is run through
        ``dlp_engine.mask()`` before delivery so PII never reaches the SIEM.
    buffer_size:
        Maximum pending events in the ring buffer.  When full the *oldest*
        event is evicted and ``overflow_count`` is incremented.
    flush_interval:
        Seconds between flush cycles (default 2.0).
    failsafe_path:
        Path to the failsafe JSONL file written when all transports fail after
        all retries.
    """

    def __init__(
        self,
        transports: List[BaseSIEMTransport],
        formatter: CEFFormatter,
        dlp_engine: Any = None,          # Optional[DLPEngine] — avoid hard import
        buffer_size: int = 10_000,
        flush_interval: float = 2.0,
        failsafe_path: str = "/var/log/ironcore/siem-failsafe.log",
    ) -> None:
        check_enterprise("siem_integration")
        self._transports = list(transports)
        self._formatter = formatter
        self._dlp = dlp_engine
        self._buffer_size = buffer_size
        self._flush_interval = flush_interval
        self._failsafe_path = Path(failsafe_path)

        # Internal ring buffer (deque with maxlen acts as circular buffer)
        self._buffer: Deque[AuditLogEntry] = deque(maxlen=buffer_size)
        self._lock = asyncio.Lock()

        self._overflow_count: int = 0
        self._sent_count: int = 0
        self._failed_count: int = 0

        self._flush_task: Optional[asyncio.Task] = None
        self._running: bool = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background flush loop."""
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(
            self._flush_loop(), name="ironcore-siem-flush"
        )
        logger.info(
            "[SIEMStreamer] Started — %d transports, buffer=%d, interval=%.1fs",
            len(self._transports),
            self._buffer_size,
            self._flush_interval,
        )

    async def stop(self) -> None:
        """Flush remaining events then stop the background task."""
        self._running = False
        if self._flush_task:
            # One final flush before cancelling
            await self._flush_once()
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        logger.info(
            "[SIEMStreamer] Stopped — sent=%d, failed=%d, overflow=%d",
            self._sent_count,
            self._failed_count,
            self._overflow_count,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def emit(self, entry: AuditLogEntry) -> None:
        """Non-blocking: add entry to ring buffer.

        If the buffer is full the oldest entry is evicted (deque maxlen handles
        this automatically) and the overflow counter is incremented.
        """
        async with self._lock:
            before = len(self._buffer)
            self._buffer.append(entry)
            after = len(self._buffer)
            if after <= before and before == self._buffer_size:
                # deque evicted the oldest — count overflow
                self._overflow_count += 1
                logger.warning(
                    "[SIEMStreamer] Buffer full (%d) — oldest event evicted. overflow_total=%d",
                    self._buffer_size,
                    self._overflow_count,
                )

    def emit_sync(self, entry: AuditLogEntry) -> None:
        """Synchronous emit — safe to call outside an async context.

        Uses a best-effort approach: if no event loop is running the entry is
        written directly to the failsafe file.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.emit(entry))
        except RuntimeError:
            # No running event loop — write to failsafe directly
            self._write_failsafe_sync([entry])

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _flush_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
                await self._flush_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("[SIEMStreamer] Flush loop error: %s", exc)

    async def _flush_once(self) -> None:
        """Drain the current buffer and ship to all transports."""
        async with self._lock:
            if not self._buffer:
                return
            batch = list(self._buffer)
            self._buffer.clear()

        # Format → optionally mask PII → deliver
        cef_lines = self._formatter.format_batch(batch)
        if self._dlp is not None:
            cef_lines = [self._dlp.mask(line) for line in cef_lines]

        if not cef_lines:
            return

        # Fan-out to all transports in parallel
        tasks = [
            self._send_with_retry(transport, cef_lines)
            for transport in self._transports
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Tally outcomes — at least one success counts as sent
        success = any(r is None for r in results)
        if success:
            self._sent_count += len(cef_lines)
        else:
            self._failed_count += len(cef_lines)
            await self._write_failsafe(batch)

    async def _send_with_retry(
        self, transport: BaseSIEMTransport, events: List[str]
    ) -> None:
        """Send with exponential backoff retries.

        Raises the last exception if all retries are exhausted.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_RETRY):
            try:
                await transport.send(events)
                return  # success
            except Exception as exc:
                last_exc = exc
                wait = _RETRY_BASE * (2 ** attempt)
                logger.warning(
                    "[SIEMStreamer] Transport %s failed (attempt %d/%d): %s — retry in %.1fs",
                    type(transport).__name__,
                    attempt + 1,
                    _MAX_RETRY,
                    exc,
                    wait,
                )
                if attempt < _MAX_RETRY - 1:
                    await asyncio.sleep(wait)
        raise last_exc  # type: ignore[misc]

    async def _write_failsafe(self, entries: List[AuditLogEntry]) -> None:
        """Append failed entries as JSONL to the failsafe file."""
        try:
            self._failsafe_path.parent.mkdir(parents=True, exist_ok=True)
            with self._failsafe_path.open("a", encoding="utf-8") as fh:
                for entry in entries:
                    fh.write(entry.model_dump_json() + "\n")
            logger.error(
                "[SIEMStreamer] Wrote %d events to failsafe: %s",
                len(entries),
                self._failsafe_path,
            )
        except OSError as exc:
            logger.error("[SIEMStreamer] Could not write failsafe: %s", exc)

    def _write_failsafe_sync(self, entries: List[AuditLogEntry]) -> None:
        """Synchronous variant of _write_failsafe (no async context)."""
        try:
            self._failsafe_path.parent.mkdir(parents=True, exist_ok=True)
            with self._failsafe_path.open("a", encoding="utf-8") as fh:
                for entry in entries:
                    fh.write(entry.model_dump_json() + "\n")
        except OSError as exc:
            logger.error("[SIEMStreamer] Failsafe write error: %s", exc)

    # ── Stats ─────────────────────────────────────────────────────────────────

    @property
    def overflow_count(self) -> int:
        return self._overflow_count

    @property
    def sent_count(self) -> int:
        return self._sent_count

    @property
    def failed_count(self) -> int:
        return self._failed_count

    @property
    def buffer_len(self) -> int:
        return len(self._buffer)

    # ── Factory ────────────────────────────────────────────────────────────────

    @classmethod
    def from_env(
        cls,
        transports: Optional[List[BaseSIEMTransport]] = None,
        dlp_engine: Any = None,
        http_client: Any = None,
    ) -> "SIEMStreamer":
        """Build a SIEMStreamer from environment variables.

        ``IRONCORE_SIEM_TRANSPORTS`` is a comma-separated list of transport
        names (``splunk``, ``syslog``, ``datadog``).
        """
        from ironcore.enterprise.siem.transports import (
            DatadogTransport,
            SplunkHECTransport,
            SyslogTCPTransport,
        )

        if transports is None:
            enabled = os.getenv("IRONCORE_SIEM_TRANSPORTS", "splunk").split(",")
            transports = []
            for name in enabled:
                name = name.strip().lower()
                if name == "splunk":
                    transports.append(SplunkHECTransport.from_env(http_client=http_client))
                elif name == "syslog":
                    transports.append(SyslogTCPTransport.from_env())
                elif name == "datadog":
                    transports.append(DatadogTransport.from_env(http_client=http_client))
                else:
                    logger.warning("[SIEMStreamer] Unknown transport name: %r — skipped", name)

        return cls(
            transports=transports,
            formatter=CEFFormatter.from_env(),
            dlp_engine=dlp_engine,
            buffer_size=int(os.getenv("IRONCORE_SIEM_BUFFER_SIZE", "10000")),
            flush_interval=float(os.getenv("IRONCORE_SIEM_FLUSH_INTERVAL", "2.0")),
            failsafe_path=os.getenv(
                "IRONCORE_SIEM_FAILSAFE_PATH", "/var/log/ironcore/siem-failsafe.log"
            ),
        )
