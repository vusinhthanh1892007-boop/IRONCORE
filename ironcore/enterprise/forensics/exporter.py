"""
Forensics Exporter — Phase 2, Security V3.

Builds an evidence export bundle from a forensics session:
  - JSON format (full timeline, session metadata, chain verification)
  - CSV format (flat event log for SIEM / spreadsheet import)

Privacy: user prompt text is NEVER in the export (only hashes).
Secrets: masked before storage, never appear in exports.

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
from typing import Dict, Any, List, Optional

from ironcore.enterprise.forensics.recorder import ForensicsRecorder, ForensicsSessionInfo

logger = logging.getLogger(__name__)

# Max events per export to prevent OOM on huge sessions
_EXPORT_LIMIT = 50_000


class ForensicsExporter:
    """
    Export forensics sessions to JSON or CSV evidence bundles.

    Usage::

        exporter = ForensicsExporter(recorder)
        bundle = await exporter.export_json("sess-abc", verify_chain=True)
        csv_text = await exporter.export_csv("sess-abc")
    """

    def __init__(self, recorder: ForensicsRecorder) -> None:
        self._recorder = recorder

    # ── JSON export ───────────────────────────────────────────────────────────

    async def export_json(
        self,
        session_id: str,
        verify_chain: bool = True,
        requester_id: str = "admin",
    ) -> Dict[str, Any]:
        """
        Build a full JSON evidence bundle for one session.

        Structure::

            {
              "export_meta": {...},
              "session": {...},
              "chain_integrity": {...},
              "timeline": [{...event...}, ...],
            }

        Chain verification is run before export — the result is embedded.
        """
        session_info: Optional[ForensicsSessionInfo] = await self._recorder.get_session_info(session_id)
        if session_info is None:
            raise ValueError(f"No forensics data for session '{session_id}'")

        events = await self._recorder.get_timeline(session_id, limit=_EXPORT_LIMIT)

        chain_result: Dict[str, Any] = {}
        if verify_chain:
            is_valid, errors = await self._recorder.verify_chain(session_id)
            chain_result = {
                "valid": is_valid,
                "errors": errors,
                "verified_at": time.time(),
            }
        else:
            chain_result = {"valid": None, "errors": [], "verified_at": None}

        event_rows = [
            {
                "seq": e.sequence_number,
                "event_id": e.event_id,
                "event_type": e.event_type.value,
                "timestamp": e.timestamp,
                "metadata": e.metadata,
                "chain_hash": e.chain_hash,
                "prev_hash": e.prev_hash,
            }
            for e in events
        ]

        bundle = {
            "export_meta": {
                "export_format": "ironcore_forensics_v1",
                "exported_at": time.time(),
                "exported_by": requester_id,
                "event_count": len(event_rows),
                "privacy_note": (
                    "User prompt content is hashed (SHA-256) — raw text is NEVER stored. "
                    "Tool arguments have secrets masked."
                ),
            },
            "session": {
                "session_id": session_info.session_id,
                "agent_id": session_info.agent_id,
                "user_id": session_info.user_id,   # already masked
                "started_at": session_info.started_at,
                "ended_at": session_info.ended_at,
                "event_count": session_info.event_count,
                "genesis_hash": session_info.genesis_hash,
            },
            "chain_integrity": chain_result,
            "timeline": event_rows,
        }

        logger.info(
            "[ForensicsExporter] JSON export | session=%s events=%d chain_valid=%s by=%s",
            session_id, len(event_rows), chain_result.get("valid"), requester_id,
        )
        return bundle

    # ── CSV export ────────────────────────────────────────────────────────────

    async def export_csv(
        self,
        session_id: str,
        requester_id: str = "admin",
    ) -> str:
        """
        Build a flat CSV evidence log for one session.

        Columns: seq, event_id, event_type, timestamp_iso, metadata_json, chain_hash_prefix
        """
        events = await self._recorder.get_timeline(session_id, limit=_EXPORT_LIMIT)

        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)

        # Header
        writer.writerow([
            "seq", "event_id", "event_type",
            "timestamp", "metadata_json", "chain_hash_prefix",
        ])

        for e in events:
            writer.writerow([
                e.sequence_number,
                e.event_id,
                e.event_type.value,
                f"{e.timestamp:.3f}",
                json.dumps(e.metadata, ensure_ascii=False),
                e.chain_hash[:16],   # prefix only — no full hash in CSV
            ])

        csv_text = output.getvalue()
        logger.info(
            "[ForensicsExporter] CSV export | session=%s events=%d by=%s",
            session_id, len(events), requester_id,
        )
        return csv_text

    # ── Summary stats ─────────────────────────────────────────────────────────

    async def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """
        Return a summary dict for the Forensics UI session detail panel.
        """
        info = await self._recorder.get_session_info(session_id)
        if info is None:
            return {}

        events = await self._recorder.get_timeline(session_id, limit=_EXPORT_LIMIT)

        # Count by type
        type_counts: Dict[str, int] = {}
        for e in events:
            type_counts[e.event_type.value] = type_counts.get(e.event_type.value, 0) + 1

        duration = (info.ended_at - info.started_at) if info.ended_at else None

        return {
            "session_id": session_id,
            "agent_id": info.agent_id,
            "user_id": info.user_id,
            "started_at": info.started_at,
            "ended_at": info.ended_at,
            "duration_seconds": round(duration, 2) if duration else None,
            "total_events": len(events),
            "event_type_counts": type_counts,
            "chain_valid": info.chain_valid,
            "genesis_hash": info.genesis_hash,
        }
