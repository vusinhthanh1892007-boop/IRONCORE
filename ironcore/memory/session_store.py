"""
IronCore: SQLite Persistent Session Manager
============================================
Phase 5 — The Brain (Claude Sonnet 4.6)

Responsibilities:
  - Persistent session state across agent runs (create, get, update, list)
  - Full message history per session with role-based storage
  - Binary artifact storage (screenshots, files, code snippets)
  - GDPR-compliant cleanup of old sessions
  - Forward-only schema migration system
  - Async-first design via aiosqlite

Schema (v1):
  sessions   — session metadata, state, agent_id, timestamps
  messages   — chat history linked to sessions (role, content, tool info)
  artifacts  — binary blobs linked to sessions (file, screenshot, code)
  schema_meta — internal migration version tracking

Author: The Brain (IronCore Project)
"""

from __future__ import annotations

import logging
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Exception Hierarchy
# ──────────────────────────────────────────────────────────────────────────────


class SessionStoreError(Exception):
    """Base exception for all SessionStore errors."""


class SessionNotFoundError(SessionStoreError):
    """Raised when a requested session does not exist."""


class ArtifactNotFoundError(SessionStoreError):
    """Raised when a requested artifact does not exist."""


class MigrationError(SessionStoreError):
    """Raised when a schema migration fails."""


# ──────────────────────────────────────────────────────────────────────────────
# Data Models (Pydantic V2)
# ──────────────────────────────────────────────────────────────────────────────


class SessionState(str, Enum):
    """Lifecycle states for a session."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class Session(BaseModel):
    """Metadata record for one agent session."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    state: SessionState = SessionState.ACTIVE
    metadata: Dict[str, Any] = Field(default_factory=dict)
    agent_id: str
    parent_session_id: Optional[str] = None

    @field_validator("agent_id")
    @classmethod
    def agent_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("agent_id cannot be empty")
        return v.strip()


class SessionMessage(BaseModel):
    """One message in a session's conversation history."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    timestamp: float = Field(default_factory=time.time)
    role: str  # "user" | "assistant" | "tool" | "system"
    content: str
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tokens: Optional[int] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {"user", "assistant", "tool", "system"}
        if v not in allowed:
            raise ValueError(f"role must be one of {allowed}, got '{v}'")
        return v


class SessionArtifact(BaseModel):
    """Binary artifact attached to a session."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    artifact_type: str  # "file" | "screenshot" | "code" | "data"
    name: str
    content: bytes
    mime_type: str
    created_at: float = Field(default_factory=time.time)

    @field_validator("artifact_type")
    @classmethod
    def validate_artifact_type(cls, v: str) -> str:
        allowed = {"file", "screenshot", "code", "data"}
        if v not in allowed:
            raise ValueError(f"artifact_type must be one of {allowed}, got '{v}'")
        return v


# ──────────────────────────────────────────────────────────────────────────────
# Migration Scripts (forward-only)
# ──────────────────────────────────────────────────────────────────────────────

_SCHEMA_VERSION = 1

_MIGRATIONS: Dict[int, str] = {
    1: """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id                TEXT PRIMARY KEY,
            created_at        REAL NOT NULL,
            updated_at        REAL NOT NULL,
            state             TEXT NOT NULL DEFAULT 'active',
            metadata_json     TEXT NOT NULL DEFAULT '{}',
            agent_id          TEXT NOT NULL,
            parent_session_id TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_agent_id ON sessions(agent_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_state    ON sessions(state);
        CREATE INDEX IF NOT EXISTS idx_sessions_created  ON sessions(created_at);

        CREATE TABLE IF NOT EXISTS messages (
            id            TEXT PRIMARY KEY,
            session_id    TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            timestamp     REAL NOT NULL,
            role          TEXT NOT NULL,
            content       TEXT NOT NULL,
            tool_name     TEXT,
            tool_args_json TEXT,
            tokens        INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
        CREATE INDEX IF NOT EXISTS idx_messages_timestamp  ON messages(timestamp);

        CREATE TABLE IF NOT EXISTS artifacts (
            id            TEXT PRIMARY KEY,
            session_id    TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            artifact_type TEXT NOT NULL,
            name          TEXT NOT NULL,
            content       BLOB NOT NULL,
            mime_type     TEXT NOT NULL,
            created_at    REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_artifacts_session_id ON artifacts(session_id);
    """,
}


# ──────────────────────────────────────────────────────────────────────────────
# SessionStore
# ──────────────────────────────────────────────────────────────────────────────


class SessionStore:
    """
    Async SQLite-backed persistent session manager.

    Usage:
        store = SessionStore()               # default path ~/.ironcore/sessions.db
        await store.initialize()             # create tables / run migrations

        session = await store.create_session(metadata={"task": "web_scrape"}, agent_id="brain")
        await store.add_message(session.id, SessionMessage(session_id=session.id, role="user", content="hello"))
        msgs = await store.get_messages(session.id)
        await store.update_session_state(session.id, SessionState.COMPLETED)
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            default_dir = Path.home() / ".ironcore"
            default_dir.mkdir(parents=True, exist_ok=True)
            db_path = default_dir / "sessions.db"
        self._db_path = Path(db_path).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Create tables and run pending migrations. Idempotent."""
        if self._initialized:
            return
        async with self._connect() as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA foreign_keys=ON;")
            await self._run_migrations(db)
        self._initialized = True
        logger.info("[SessionStore] Initialized db_path=%s", self._db_path)

    async def close(self) -> None:
        """No persistent connection to close (connections are per-operation)."""
        self._initialized = False
        logger.info("[SessionStore] Closed.")

    # ── Session Operations ────────────────────────────────────────────────────

    async def create_session(
        self,
        metadata: Dict[str, Any],
        agent_id: str,
        parent_session_id: Optional[str] = None,
    ) -> Session:
        """Create and persist a new session. Returns the created Session."""
        import json

        session = Session(
            metadata=metadata,
            agent_id=agent_id,
            parent_session_id=parent_session_id,
        )
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO sessions
                    (id, created_at, updated_at, state, metadata_json, agent_id, parent_session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.created_at,
                    session.updated_at,
                    session.state.value,
                    json.dumps(session.metadata),
                    session.agent_id,
                    session.parent_session_id,
                ),
            )
            await db.commit()

        logger.info("[SessionStore] Created session id=%s agent=%s", session.id, agent_id)
        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Return a Session by ID, or None if not found."""
        import json

        async with self._connect() as db:
            async with db.execute(
                "SELECT id, created_at, updated_at, state, metadata_json, agent_id, parent_session_id "
                "FROM sessions WHERE id = ?",
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()

        if row is None:
            return None

        return Session(
            id=row[0],
            created_at=row[1],
            updated_at=row[2],
            state=SessionState(row[3]),
            metadata=json.loads(row[4]),
            agent_id=row[5],
            parent_session_id=row[6],
        )

    async def update_session_state(self, session_id: str, state: SessionState) -> None:
        """Update the lifecycle state and updated_at timestamp of a session."""
        now = time.time()
        async with self._connect() as db:
            result = await db.execute(
                "UPDATE sessions SET state = ?, updated_at = ? WHERE id = ?",
                (state.value, now, session_id),
            )
            await db.commit()

        if result.rowcount == 0:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        logger.debug("[SessionStore] Session %s → state=%s", session_id, state.value)

    async def list_sessions(
        self,
        agent_id: Optional[str] = None,
        state: Optional[SessionState] = None,
    ) -> List[Session]:
        """Return sessions, optionally filtered by agent_id and/or state."""
        import json

        conditions: list[str] = []
        params: list[Any] = []

        if agent_id is not None:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if state is not None:
            conditions.append("state = ?")
            params.append(state.value)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = (
            f"SELECT id, created_at, updated_at, state, metadata_json, agent_id, parent_session_id "
            f"FROM sessions {where} ORDER BY created_at DESC"
        )

        async with self._connect() as db:
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()

        return [
            Session(
                id=row[0],
                created_at=row[1],
                updated_at=row[2],
                state=SessionState(row[3]),
                metadata=json.loads(row[4]),
                agent_id=row[5],
                parent_session_id=row[6],
            )
            for row in rows
        ]

    # ── Message Operations ────────────────────────────────────────────────────

    async def add_message(self, session_id: str, message: SessionMessage) -> None:
        """Append a message to the session's conversation history."""
        import json

        if message.session_id != session_id:
            raise ValueError(
                f"message.session_id={message.session_id!r} != session_id={session_id!r}"
            )

        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO messages
                    (id, session_id, timestamp, role, content, tool_name, tool_args_json, tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id,
                    session_id,
                    message.timestamp,
                    message.role,
                    message.content,
                    message.tool_name,
                    json.dumps(message.tool_args) if message.tool_args is not None else None,
                    message.tokens,
                ),
            )
            # bump session updated_at
            await db.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (time.time(), session_id),
            )
            await db.commit()

        logger.debug(
            "[SessionStore] Message added session=%s role=%s", session_id, message.role
        )

    async def get_messages(
        self,
        session_id: str,
        last_n: Optional[int] = None,
    ) -> List[SessionMessage]:
        """
        Return the message history for a session, oldest first.

        Args:
            session_id: Target session UUID.
            last_n:     If given, return only the most recent N messages.
        """
        import json

        if last_n is not None and last_n <= 0:
            return []

        if last_n is not None:
            query = (
                "SELECT id, session_id, timestamp, role, content, tool_name, tool_args_json, tokens "
                "FROM messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?"
            )
            params: tuple[Any, ...] = (session_id, last_n)
        else:
            query = (
                "SELECT id, session_id, timestamp, role, content, tool_name, tool_args_json, tokens "
                "FROM messages WHERE session_id = ? ORDER BY timestamp ASC"
            )
            params = (session_id,)

        async with self._connect() as db:
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()

        messages = [
            SessionMessage(
                id=row[0],
                session_id=row[1],
                timestamp=row[2],
                role=row[3],
                content=row[4],
                tool_name=row[5],
                tool_args=json.loads(row[6]) if row[6] is not None else None,
                tokens=row[7],
            )
            for row in rows
        ]

        # DESC fetch → reverse to get ascending order
        if last_n is not None:
            messages.reverse()

        return messages

    # ── Artifact Operations ───────────────────────────────────────────────────

    async def store_artifact(self, session_id: str, artifact: SessionArtifact) -> None:
        """Persist a binary artifact attached to a session."""
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO artifacts
                    (id, session_id, artifact_type, name, content, mime_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.id,
                    session_id,
                    artifact.artifact_type,
                    artifact.name,
                    artifact.content,
                    artifact.mime_type,
                    artifact.created_at,
                ),
            )
            await db.commit()

        logger.debug(
            "[SessionStore] Artifact stored session=%s type=%s name=%s",
            session_id,
            artifact.artifact_type,
            artifact.name,
        )

    async def get_artifact(self, artifact_id: str) -> Optional[SessionArtifact]:
        """Return an artifact by ID, or None if not found."""
        async with self._connect() as db:
            async with db.execute(
                "SELECT id, session_id, artifact_type, name, content, mime_type, created_at "
                "FROM artifacts WHERE id = ?",
                (artifact_id,),
            ) as cursor:
                row = await cursor.fetchone()

        if row is None:
            return None

        return SessionArtifact(
            id=row[0],
            session_id=row[1],
            artifact_type=row[2],
            name=row[3],
            content=bytes(row[4]),
            mime_type=row[5],
            created_at=row[6],
        )

    # ── Maintenance ───────────────────────────────────────────────────────────

    async def cleanup_old_sessions(self, older_than_days: int = 30) -> int:
        """
        Delete sessions (and their cascaded messages/artifacts) older than N days.

        Returns:
            Number of sessions deleted.
        """
        if older_than_days <= 0:
            raise ValueError("older_than_days must be positive")

        cutoff = time.time() - (older_than_days * 86_400)

        async with self._connect() as db:
            cursor = await db.execute(
                "DELETE FROM sessions WHERE created_at < ? AND state != ?",
                (cutoff, SessionState.ACTIVE.value),
            )
            deleted = cursor.rowcount
            await db.commit()

        logger.info(
            "[SessionStore] Cleaned up %d sessions older than %d days",
            deleted,
            older_than_days,
        )
        return deleted

    # ── Internal Helpers ──────────────────────────────────────────────────────

    def _connect(self) -> aiosqlite.Connection:
        """Return an aiosqlite connection context manager."""
        return aiosqlite.connect(str(self._db_path))

    async def _run_migrations(self, db: aiosqlite.Connection) -> None:
        """Apply any pending forward-only migrations."""
        # Read current version
        try:
            async with db.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ) as cursor:
                row = await cursor.fetchone()
                current_version = int(row[0]) if row else 0
        except aiosqlite.OperationalError:
            # schema_meta table doesn't exist yet — first run
            current_version = 0

        if current_version >= _SCHEMA_VERSION:
            logger.debug(
                "[SessionStore] Schema already at version %d — no migrations needed.",
                current_version,
            )
            return

        for version in sorted(_MIGRATIONS.keys()):
            if version <= current_version:
                continue

            logger.info("[SessionStore] Applying migration v%d …", version)
            try:
                await db.executescript(_MIGRATIONS[version])
                await db.execute(
                    "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
                    (str(version),),
                )
                await db.commit()
                logger.info("[SessionStore] Migration v%d applied.", version)
            except Exception as exc:
                raise MigrationError(f"Migration v{version} failed: {exc}") from exc
