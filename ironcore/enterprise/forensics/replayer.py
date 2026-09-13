"""
Forensics Replayer — Phase 2, Security V3.

Reads a forensics session timeline from ForensicsRecorder and replays it
as a Server-Sent Events (SSE) stream — preserving original timing gaps.

This powers the Forensics Replay UI built by ChatGPT UI V3.

Features:
  - Real-time replay with original timing (2× or 5× speed options)
  - Jump to timestamp
  - Filter by event_type
  - Streaming via AsyncGenerator[str, None] (FastAPI StreamingResponse)

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncGenerator, List, Optional

from ironcore.enterprise.forensics.recorder import ForensicsEvent, ForensicsRecorder

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_GAP_SECONDS = 5.0     # cap timing gaps so replay doesn't stall too long
VALID_SPEEDS = {0.5, 1.0, 2.0, 5.0, 10.0}


# ── ForensicsReplayer ─────────────────────────────────────────────────────────

class ForensicsReplayer:
    """
    Replay a forensics session timeline as SSE events.

    Args:
        recorder: Shared ForensicsRecorder instance to pull events from.
    """

    def __init__(self, recorder: ForensicsRecorder) -> None:
        self._recorder = recorder

    async def replay_stream(
        self,
        session_id: str,
        speed: float = 2.0,
        from_timestamp: Optional[float] = None,
        event_types: Optional[List[str]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Yield SSE-formatted strings for each forensics event, replayed at *speed*×.

        Args:
            session_id:     The session to replay.
            speed:          Playback speed multiplier (1.0 = real-time, 2.0 = 2× faster).
            from_timestamp: Start replay from this Unix timestamp (skip earlier events).
            event_types:    If given, only yield events of these types.

        Yields:
            SSE-formatted strings: "data: {...json...}\n\n"
        """
        if speed not in VALID_SPEEDS:
            speed = 2.0

        events = await self._recorder.get_timeline(session_id, limit=10_000)
        if not events:
            yield _sse_event({"type": "replay_empty", "session_id": session_id})
            return

        # Filter
        if from_timestamp is not None:
            events = [e for e in events if e.timestamp >= from_timestamp]
        if event_types:
            events = [e for e in events if e.event_type.value in event_types]

        session_info = await self._recorder.get_session_info(session_id)

        # Send replay_start header
        yield _sse_event({
            "type": "replay_start",
            "session_id": session_id,
            "event_count": len(events),
            "speed": speed,
            "agent_id": session_info.agent_id if session_info else "",
            "started_at": session_info.started_at if session_info else None,
        })

        prev_ts: Optional[float] = None

        for i, event in enumerate(events):
            # Preserve original timing gap (capped), divided by speed
            if prev_ts is not None:
                raw_gap = event.timestamp - prev_ts
                gap = min(raw_gap, MAX_GAP_SECONDS) / speed
                if gap > 0.01:
                    await asyncio.sleep(gap)

            prev_ts = event.timestamp

            payload = {
                "type": "replay_event",
                "seq": event.sequence_number,
                "event_type": event.event_type.value,
                "timestamp": event.timestamp,
                "event_id": event.event_id,
                "metadata": event.metadata,
                "chain_hash_prefix": event.chain_hash[:8],  # for UI integrity indicator
                "progress": round((i + 1) / len(events), 4),
            }
            yield _sse_event(payload)

        yield _sse_event({
            "type": "replay_complete",
            "session_id": session_id,
            "total_events": len(events),
        })
        logger.info(
            "[ForensicsReplayer] Replay complete | session=%s events=%d speed=%.1f",
            session_id, len(events), speed,
        )

    async def get_event_at_timestamp(
        self,
        session_id: str,
        target_ts: float,
    ) -> Optional[ForensicsEvent]:
        """
        Return the event closest to *target_ts* for jump-to feature.
        """
        events = await self._recorder.get_timeline(session_id, limit=10_000)
        if not events:
            return None
        # Find closest by absolute timestamp difference
        closest = min(events, key=lambda e: abs(e.timestamp - target_ts))
        return closest


# ── SSE helpers ────────────────────────────────────────────────────────────────

def _sse_event(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
