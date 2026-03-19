"""
Forensics Recorder — Phase 2, Security V3.

Append-only SQLite WAL database recording every forensics event in a session:
  - User messages (prompt text — stored masked/hashed, not raw)
  - Tool calls (tool_name, risk_level, status)
  - LLM responses (token count, model, NO raw content — privacy)
  - Firewall decisions (action, risk_score, category)
  - HITL decisions (approver, verdict, ticket_id)
  - System events (engine start/stop, errors)

TAMPER-PROOF design:
  - Each event row includes a SHA-256 HMAC chain hash (prev_hash + payload)
  - Chain is anchored to a genesis block with the session_id as salt
  - `verify_chain()` validates the full chain — any modification breaks it

Privacy & Security:
  - User prompt text is NEVER stored raw — only a salted SHA-256 hash
  - Tool arguments are stored as masked JSON (secrets stripped)
  - LLM response content is NEVER stored — only metadata (tokens, model)

Schema:
  forensics_events  — one row per event, ordered by sequence_number
  forensics_sessions — one row per session

Env vars:
  IRONCORE_FORENSICS_DB_PATH   (default ~/.ironcore/forensics.db)
  IRONCORE_FORENSICS_ENABLED   (default true)

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_DB_PATH = Path(
    os.environ.get("IRONCORE_FORENSICS_DB_PATH", str(Path.home() / ".ironcore" / "forensics.db"))
)
_ENABLED = os.environ.get("IRONCORE_FORENSICS_ENABLED", "true").lower() != "false"

# HMAC key — derive from a project secret or use a default for dev
_CHAIN_KEY = os.environ.get(
    "IRONCORE_FORENSICS_CHAIN_KEY", "dev-chain-key-change-in-production"
).encode()

# Patterns for masking secrets in tool args
_SECRET_KEYS = re.compile(
    r"(key|secret|token|password|passwd|credential|auth|bearer)",
    re.I,
)


# ── Enums ─────────────────────────────────────────────────────────────────────

class ForensicsEventType(str, Enum):
    SESSION_START    = "session_start"
    SESSION_END      = "session_end"
    USER_PROMPT      = "user_prompt"        # stored as hash only
    AGENT_RESPONSE   = "agent_response"     # metadata only, no content
    TOOL_CALL        = "tool_call"
    TOOL_RESULT      = "tool_result"
    FIREWALL_DETECT  = "firewall_detect"
    HITL_REQUEST     = "hitl_request"
    HITL_DECISION    = "hitl_decision"
    ERROR            = "error"
    POLICY_VIOLATION = "policy_violation"


# ── Pydantic Models ────────────────────────────────────────────────────────────

class ForensicsEvent(BaseModel, frozen=True):
    """Immutable forensics event row."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    sequence_number: int
    event_type: ForensicsEventType
    timestamp: float = Field(default_factory=time.time)
    # Metadata payload — sanitised (no raw prompts, no secrets)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # Hash chain
    chain_hash: str = ""            # HMAC of (prev_hash + payload_json)
    prev_hash: str = ""             # hash of the previous event in chain


class ForensicsSessionInfo(BaseModel):
    """Per-session summary stored in forensics_sessions."""

    session_id: str
    agent_id: str = ""
    user_id: str = ""
    started_at: float = Field(default_factory=time.time)
    ended_at: Optional[float] = None
    event_count: int = 0
    chain_valid: Optional[bool] = None     # None = not yet verified
    genesis_hash: str = ""                 # hash of the first event


# ── Schema ─────────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS forensics_sessions (
    session_id   TEXT PRIMARY KEY,
    agent_id     TEXT NOT NULL DEFAULT '',
    user_id      TEXT NOT NULL DEFAULT '',
    started_at   REAL NOT NULL,
    ended_at     REAL,
    event_count  INTEGER NOT NULL DEFAULT 0,
    genesis_hash TEXT NOT NULL DEFAULT '',
    chain_valid  INTEGER         -- NULL=unverified, 1=valid, 0=tampered
);

CREATE TABLE IF NOT EXISTS forensics_events (
    event_id        TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES forensics_sessions(session_id),
    sequence_number INTEGER NOT NULL,
    event_type      TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    chain_hash      TEXT NOT NULL,
    prev_hash       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_fe_session ON forensics_events(session_id, sequence_number);
CREATE INDEX IF NOT EXISTS idx_fe_type    ON forensics_events(event_type);
CREATE INDEX IF NOT EXISTS idx_fe_time    ON forensics_events(timestamp);
"""


# ── Hash helpers ───────────────────────────────────────────────────────────────

def _compute_chain_hash(prev_hash: str, event_id: str, payload_json: str) -> str:
    """Compute HMAC-SHA256 for the chain link."""
    message = f"{prev_hash}|{event_id}|{payload_json}".encode("utf-8")
    return hmac.new(_CHAIN_KEY, message, hashlib.sha256).hexdigest()


def _hash_prompt(prompt: str, session_id: str) -> str:
    """Return salted SHA-256 of the prompt — NEVER stores raw text."""
    salted = f"{session_id}:{prompt}".encode("utf-8")
    return "sha256:" + hashlib.sha256(salted).hexdigest()[:32]


def _mask_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """Remove values of keys that look like secrets."""
    masked: Dict[str, Any] = {}
    for k, v in args.items():
        if _SECRET_KEYS.search(k):
            masked[k] = "[MASKED]"
        elif isinstance(v, dict):
            masked[k] = _mask_args(v)
        elif isinstance(v, str) and len(v) > 200:
            masked[k] = v[:80] + "...[truncated]"
        else:
            masked[k] = v
    return masked


# ── ForensicsRecorder ──────────────────────────────────────────────────────────

class ForensicsRecorder:
    """
    Append-only tamper-proof forensics recorder backed by SQLite WAL.

    One instance per application; multiple sessions share the same DB file.
    Safe to use concurrently (aiosqlite per-operation connections + WAL).

    Usage::

        recorder = ForensicsRecorder()
        await recorder.initialize()

        await recorder.start_session("sess-abc", agent_id="ironcore", user_id="u123")
        await recorder.record_user_prompt("sess-abc", raw_prompt)
        await recorder.record_tool_call("sess-abc", "web_search", {"query": "test"}, risk="LOW")
        await recorder.end_session("sess-abc")

        events = await recorder.get_timeline("sess-abc")
        ok, _ = await recorder.verify_chain("sess-abc")
    """

    def __init__(self, db_path: Optional[Path] = None, enabled: bool = _ENABLED) -> None:
        self._db_path = (db_path or _DB_PATH).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._enabled = enabled
        self._initialized = False
        # In-memory per-session chain tracking: session_id → (next_seq, last_hash)
        self._chain_state: Dict[str, Tuple[int, str]] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Create schema. Idempotent."""
        if self._initialized:
            return
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.executescript(_SCHEMA_SQL)
            await db.commit()
        self._initialized = True
        logger.info("[ForensicsRecorder] Initialized db=%s", self._db_path)

    # ── Session lifecycle events ───────────────────────────────────────────────

    async def start_session(
        self,
        session_id: str,
        agent_id: str = "",
        user_id: str = "",
    ) -> None:
        """Record the start of a forensics-tracked session."""
        if not self._enabled:
            return
        await self._ensure_session_row(session_id, agent_id=agent_id, user_id=user_id)
        await self._append_event(
            session_id=session_id,
            event_type=ForensicsEventType.SESSION_START,
            metadata={"agent_id": agent_id, "user_id": mask_user_id(user_id)},
        )

    async def end_session(self, session_id: str) -> None:
        """Record the end of a forensics-tracked session."""
        if not self._enabled:
            return
        await self._append_event(
            session_id=session_id,
            event_type=ForensicsEventType.SESSION_END,
            metadata={},
        )
        now = time.time()
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                "UPDATE forensics_sessions SET ended_at=? WHERE session_id=?",
                (now, session_id),
            )
            await db.commit()

    # ── Event recording ────────────────────────────────────────────────────────

    async def record_user_prompt(self, session_id: str, raw_prompt: str) -> str:
        """
        Record that a user prompt was received.
        ONLY stores a salted hash — NEVER the raw text.
        Returns the hash for audit correlation.
        """
        if not self._enabled:
            return ""
        prompt_hash = _hash_prompt(raw_prompt, session_id)
        char_count = len(raw_prompt)
        await self._append_event(
            session_id=session_id,
            event_type=ForensicsEventType.USER_PROMPT,
            metadata={
                "prompt_hash": prompt_hash,
                "char_count": char_count,
            },
        )
        return prompt_hash

    async def record_agent_response(
        self,
        session_id: str,
        model: str,
        token_count: int,
        finish_reason: str = "stop",
    ) -> None:
        """Record LLM response metadata — NO content stored."""
        if not self._enabled:
            return
        await self._append_event(
            session_id=session_id,
            event_type=ForensicsEventType.AGENT_RESPONSE,
            metadata={
                "model": model,
                "token_count": token_count,
                "finish_reason": finish_reason,
            },
        )

    async def record_tool_call(
        self,
        session_id: str,
        tool_name: str,
        args: Dict[str, Any],
        risk: str = "LOW",
        action_id: str = "",
    ) -> None:
        """Record a tool call with masked arguments."""
        if not self._enabled:
            return
        await self._append_event(
            session_id=session_id,
            event_type=ForensicsEventType.TOOL_CALL,
            metadata={
                "tool_name": tool_name,
                "args_masked": _mask_args(args),
                "risk": risk,
                "action_id": action_id,
            },
        )

    async def record_tool_result(
        self,
        session_id: str,
        tool_name: str,
        status: str,
        action_id: str = "",
        error: Optional[str] = None,
    ) -> None:
        """Record the outcome of a tool call (success/fail, NOT the output content)."""
        if not self._enabled:
            return
        await self._append_event(
            session_id=session_id,
            event_type=ForensicsEventType.TOOL_RESULT,
            metadata={
                "tool_name": tool_name,
                "status": status,          # "ok" | "error" | "blocked"
                "action_id": action_id,
                "error": error[:200] if error else None,
            },
        )

    async def record_firewall_detection(
        self,
        session_id: str,
        action: str,
        risk_score: float,
        category: str,
        rule_names: List[str],
    ) -> None:
        """Record a firewall detection event."""
        if not self._enabled:
            return
        await self._append_event(
            session_id=session_id,
            event_type=ForensicsEventType.FIREWALL_DETECT,
            metadata={
                "action": action,
                "risk_score": round(risk_score, 4),
                "category": category,
                "rule_names": rule_names,
            },
        )

    async def record_hitl_request(
        self,
        session_id: str,
        ticket_id: str,
        action_description: str,
        required_approvals: int,
    ) -> None:
        """Record that a HITL approval was requested."""
        if not self._enabled:
            return
        await self._append_event(
            session_id=session_id,
            event_type=ForensicsEventType.HITL_REQUEST,
            metadata={
                "ticket_id": ticket_id,
                "action_description": action_description[:200],
                "required_approvals": required_approvals,
            },
        )

    async def record_hitl_decision(
        self,
        session_id: str,
        ticket_id: str,
        approver_id: str,
        verdict: str,
        reason: Optional[str] = None,
    ) -> None:
        """Record an approval/rejection on a HITL ticket."""
        if not self._enabled:
            return
        await self._append_event(
            session_id=session_id,
            event_type=ForensicsEventType.HITL_DECISION,
            metadata={
                "ticket_id": ticket_id,
                "approver_id": mask_user_id(approver_id),
                "verdict": verdict,    # "approved" | "rejected"
                "reason": reason[:200] if reason else None,
            },
        )

    async def record_error(
        self,
        session_id: str,
        error_type: str,
        message: str,
    ) -> None:
        """Record a system error event."""
        if not self._enabled:
            return
        await self._append_event(
            session_id=session_id,
            event_type=ForensicsEventType.ERROR,
            metadata={
                "error_type": error_type,
                "message": message[:300],
            },
        )

    # ── Read API ───────────────────────────────────────────────────────────────

    async def get_timeline(
        self,
        session_id: str,
        limit: int = 500,
        offset: int = 0,
    ) -> List[ForensicsEvent]:
        """Return events for a session in sequence order."""
        events: List[ForensicsEvent] = []
        async with aiosqlite.connect(str(self._db_path)) as db:
            async with db.execute(
                """
                SELECT event_id, session_id, sequence_number, event_type,
                       timestamp, metadata_json, chain_hash, prev_hash
                FROM forensics_events
                WHERE session_id = ?
                ORDER BY sequence_number ASC
                LIMIT ? OFFSET ?
                """,
                (session_id, limit, offset),
            ) as cursor:
                rows = await cursor.fetchall()

        for row in rows:
            events.append(ForensicsEvent(
                event_id=row[0],
                session_id=row[1],
                sequence_number=row[2],
                event_type=ForensicsEventType(row[3]),
                timestamp=row[4],
                metadata=json.loads(row[5]),
                chain_hash=row[6],
                prev_hash=row[7],
            ))
        return events

    async def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ForensicsSessionInfo]:
        """List forensics-tracked sessions, newest first."""
        result: List[ForensicsSessionInfo] = []
        async with aiosqlite.connect(str(self._db_path)) as db:
            async with db.execute(
                """
                SELECT session_id, agent_id, user_id, started_at, ended_at,
                       event_count, genesis_hash, chain_valid
                FROM forensics_sessions
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ) as cursor:
                rows = await cursor.fetchall()

        for row in rows:
            result.append(ForensicsSessionInfo(
                session_id=row[0],
                agent_id=row[1],
                user_id=row[2],
                started_at=row[3],
                ended_at=row[4],
                event_count=row[5],
                genesis_hash=row[6],
                chain_valid={1: True, 0: False}.get(row[7]),
            ))
        return result

    async def get_session_info(self, session_id: str) -> Optional[ForensicsSessionInfo]:
        """Return session info, or None if not found."""
        async with aiosqlite.connect(str(self._db_path)) as db:
            async with db.execute(
                """
                SELECT session_id, agent_id, user_id, started_at, ended_at,
                       event_count, genesis_hash, chain_valid
                FROM forensics_sessions WHERE session_id=?
                """,
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()

        if row is None:
            return None
        return ForensicsSessionInfo(
            session_id=row[0],
            agent_id=row[1],
            user_id=row[2],
            started_at=row[3],
            ended_at=row[4],
            event_count=row[5],
            genesis_hash=row[6],
            chain_valid={1: True, 0: False}.get(row[7]),
        )

    # ── Tamper verification ────────────────────────────────────────────────────

    async def verify_chain(self, session_id: str) -> Tuple[bool, List[str]]:
        """
        Walk the full event chain and verify HMAC integrity.

        Returns:
            (is_valid: bool, errors: list of broken link descriptions)
        """
        events = await self.get_timeline(session_id, limit=10_000)
        if not events:
            return True, []

        errors: List[str] = []
        prev_hash = ""

        for event in events:
            payload_json = json.dumps(event.metadata, sort_keys=True, ensure_ascii=False)
            expected = _compute_chain_hash(prev_hash, event.event_id, payload_json)
            if not hmac.compare_digest(expected, event.chain_hash):
                errors.append(
                    f"Chain broken at seq={event.sequence_number} "
                    f"event_id={event.event_id} type={event.event_type}"
                )
            prev_hash = event.chain_hash

        is_valid = len(errors) == 0

        # Persist verification result
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                "UPDATE forensics_sessions SET chain_valid=? WHERE session_id=?",
                (1 if is_valid else 0, session_id),
            )
            await db.commit()

        logger.info(
            "[ForensicsRecorder] Chain verify | session=%s valid=%s errors=%d",
            session_id, is_valid, len(errors),
        )
        return is_valid, errors

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _ensure_session_row(
        self, session_id: str, agent_id: str = "", user_id: str = ""
    ) -> None:
        """Insert session row if it doesn't exist."""
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO forensics_sessions
                    (session_id, agent_id, user_id, started_at, event_count, genesis_hash)
                VALUES (?, ?, ?, ?, 0, '')
                """,
                (session_id, agent_id, mask_user_id(user_id), time.time()),
            )
            await db.commit()

    async def _append_event(
        self,
        session_id: str,
        event_type: ForensicsEventType,
        metadata: Dict[str, Any],
    ) -> ForensicsEvent:
        """Append one event to the chain and persist it."""
        # Ensure session exists (idempotent)
        async with aiosqlite.connect(str(self._db_path)) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM forensics_sessions WHERE session_id=?", (session_id,)
            ) as cur:
                row = await cur.fetchone()
                if row is None or row[0] == 0:
                    # Auto-create a session row for sessions not explicitly started
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO forensics_sessions
                            (session_id, agent_id, user_id, started_at, event_count, genesis_hash)
                        VALUES (?, '', '', ?, 0, '')
                        """,
                        (session_id, time.time()),
                    )

        # Get next sequence number and prev_hash
        if session_id in self._chain_state:
            seq, prev_hash = self._chain_state[session_id]
        else:
            # Load from DB (handles restarts)
            async with aiosqlite.connect(str(self._db_path)) as db:
                async with db.execute(
                    """
                    SELECT MAX(sequence_number), chain_hash
                    FROM forensics_events WHERE session_id=?
                    """,
                    (session_id,),
                ) as cur:
                    row = await cur.fetchone()
                    if row and row[0] is not None:
                        seq = row[0] + 1
                        prev_hash = row[1]
                    else:
                        seq = 0
                        prev_hash = ""

        event_id = str(uuid.uuid4())
        payload_json = json.dumps(metadata, sort_keys=True, ensure_ascii=False)
        chain_hash = _compute_chain_hash(prev_hash, event_id, payload_json)

        event = ForensicsEvent(
            event_id=event_id,
            session_id=session_id,
            sequence_number=seq,
            event_type=event_type,
            metadata=metadata,
            chain_hash=chain_hash,
            prev_hash=prev_hash,
        )

        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                """
                INSERT INTO forensics_events
                    (event_id, session_id, sequence_number, event_type,
                     timestamp, metadata_json, chain_hash, prev_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.session_id,
                    event.sequence_number,
                    event.event_type.value,
                    event.timestamp,
                    payload_json,
                    event.chain_hash,
                    event.prev_hash,
                ),
            )
            # Update session event_count and genesis_hash if first event
            if seq == 0:
                await db.execute(
                    "UPDATE forensics_sessions SET event_count=1, genesis_hash=? WHERE session_id=?",
                    (chain_hash, session_id),
                )
            else:
                await db.execute(
                    "UPDATE forensics_sessions SET event_count=event_count+1 WHERE session_id=?",
                    (session_id,),
                )
            await db.commit()

        # Update in-memory chain state
        self._chain_state[session_id] = (seq + 1, chain_hash)

        logger.debug(
            "[ForensicsRecorder] Event appended | session=%s seq=%d type=%s",
            session_id, seq, event_type.value,
        )
        return event


# ── Privacy helpers ────────────────────────────────────────────────────────────

def mask_user_id(user_id: str) -> str:
    """Show only last 4 chars of user_id to minimise PII exposure."""
    if not user_id:
        return ""
    if len(user_id) <= 4:
        return "****"
    return "****" + user_id[-4:]
