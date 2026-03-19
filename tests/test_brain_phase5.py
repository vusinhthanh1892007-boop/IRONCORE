"""
Test Suite — Phase 5 Brain: SQLite Session Store
=================================================
Verifies:
  - Session CRUD (create, get, update_state, list)
  - Message history (add, get, get last_n, ordering)
  - Artifact storage and retrieval
  - Cleanup of old sessions (GDPR)
  - Schema migration idempotency
  - Error handling (SessionNotFoundError, validation)
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from ironcore.memory.session_store import (
    ArtifactNotFoundError,
    MigrationError,
    Session,
    SessionArtifact,
    SessionMessage,
    SessionNotFoundError,
    SessionState,
    SessionStore,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def make_store(tmp_path: Path) -> SessionStore:
    return SessionStore(db_path=tmp_path / "test_sessions.db")


async def fresh_store(tmp_path: Path) -> SessionStore:
    store = make_store(tmp_path)
    await store.initialize()
    return store


# ──────────────────────────────────────────────────────────────────────────────
# Session CRUD
# ──────────────────────────────────────────────────────────────────────────────


def test_create_and_get_session(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)

        session = await store.create_session(
            metadata={"task": "web_scrape", "url": "https://example.com"},
            agent_id="brain",
        )

        assert session.id
        assert session.state == SessionState.ACTIVE
        assert session.agent_id == "brain"
        assert session.metadata["task"] == "web_scrape"
        assert session.parent_session_id is None

        fetched = await store.get_session(session.id)
        assert fetched is not None
        assert fetched.id == session.id
        assert fetched.metadata["url"] == "https://example.com"

    asyncio.run(_run())


def test_get_session_returns_none_for_unknown_id(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        result = await store.get_session("nonexistent-uuid")
        assert result is None

    asyncio.run(_run())


def test_update_session_state(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        session = await store.create_session(metadata={}, agent_id="brain")
        assert session.state == SessionState.ACTIVE

        await store.update_session_state(session.id, SessionState.COMPLETED)

        fetched = await store.get_session(session.id)
        assert fetched is not None
        assert fetched.state == SessionState.COMPLETED

    asyncio.run(_run())


def test_update_session_state_raises_for_unknown_id(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        with pytest.raises(SessionNotFoundError):
            await store.update_session_state("ghost-id", SessionState.FAILED)

    asyncio.run(_run())


def test_session_with_parent(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        parent = await store.create_session(metadata={"root": True}, agent_id="architect")
        child = await store.create_session(
            metadata={"sub": True},
            agent_id="brain",
            parent_session_id=parent.id,
        )
        fetched = await store.get_session(child.id)
        assert fetched is not None
        assert fetched.parent_session_id == parent.id

    asyncio.run(_run())


def test_list_sessions_all(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        for i in range(3):
            await store.create_session(metadata={"i": i}, agent_id="brain")
        await store.create_session(metadata={}, agent_id="ghost")

        all_sessions = await store.list_sessions()
        assert len(all_sessions) == 4

    asyncio.run(_run())


def test_list_sessions_filter_by_agent(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        await store.create_session(metadata={}, agent_id="brain")
        await store.create_session(metadata={}, agent_id="brain")
        await store.create_session(metadata={}, agent_id="ghost")

        brain_sessions = await store.list_sessions(agent_id="brain")
        assert len(brain_sessions) == 2
        assert all(s.agent_id == "brain" for s in brain_sessions)

    asyncio.run(_run())


def test_list_sessions_filter_by_state(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        s1 = await store.create_session(metadata={}, agent_id="brain")
        s2 = await store.create_session(metadata={}, agent_id="brain")
        await store.create_session(metadata={}, agent_id="brain")

        await store.update_session_state(s1.id, SessionState.COMPLETED)
        await store.update_session_state(s2.id, SessionState.COMPLETED)

        completed = await store.list_sessions(state=SessionState.COMPLETED)
        assert len(completed) == 2

        active = await store.list_sessions(state=SessionState.ACTIVE)
        assert len(active) == 1

    asyncio.run(_run())


def test_list_sessions_filter_agent_and_state(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        s = await store.create_session(metadata={}, agent_id="brain")
        await store.create_session(metadata={}, agent_id="ghost")
        await store.update_session_state(s.id, SessionState.FAILED)

        result = await store.list_sessions(agent_id="brain", state=SessionState.FAILED)
        assert len(result) == 1
        assert result[0].agent_id == "brain"

    asyncio.run(_run())


# ──────────────────────────────────────────────────────────────────────────────
# Message History
# ──────────────────────────────────────────────────────────────────────────────


def test_add_and_get_messages(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        session = await store.create_session(metadata={}, agent_id="brain")

        msg1 = SessionMessage(session_id=session.id, role="user", content="Hello")
        msg2 = SessionMessage(session_id=session.id, role="assistant", content="Hi there!")

        await store.add_message(session.id, msg1)
        await store.add_message(session.id, msg2)

        messages = await store.get_messages(session.id)
        assert len(messages) == 2
        assert messages[0].content == "Hello"
        assert messages[1].content == "Hi there!"
        assert messages[0].role == "user"

    asyncio.run(_run())


def test_get_messages_last_n(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        session = await store.create_session(metadata={}, agent_id="brain")

        for i in range(10):
            await asyncio.sleep(0.001)  # ensure distinct timestamps
            await store.add_message(
                session.id,
                SessionMessage(session_id=session.id, role="user", content=f"msg{i}"),
            )

        last3 = await store.get_messages(session.id, last_n=3)
        assert len(last3) == 3
        # Should be the last 3 in chronological order
        assert last3[0].content == "msg7"
        assert last3[1].content == "msg8"
        assert last3[2].content == "msg9"

    asyncio.run(_run())


def test_get_messages_last_n_zero_returns_empty(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        session = await store.create_session(metadata={}, agent_id="brain")
        await store.add_message(
            session.id,
            SessionMessage(session_id=session.id, role="user", content="hi"),
        )
        result = await store.get_messages(session.id, last_n=0)
        assert result == []

    asyncio.run(_run())


def test_message_with_tool_fields(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        session = await store.create_session(metadata={}, agent_id="brain")

        msg = SessionMessage(
            session_id=session.id,
            role="tool",
            content='{"result": "ok"}',
            tool_name="web_search",
            tool_args={"query": "AI agent", "max_results": 5},
            tokens=42,
        )
        await store.add_message(session.id, msg)

        messages = await store.get_messages(session.id)
        assert len(messages) == 1
        m = messages[0]
        assert m.tool_name == "web_search"
        assert m.tool_args == {"query": "AI agent", "max_results": 5}
        assert m.tokens == 42

    asyncio.run(_run())


def test_add_message_session_id_mismatch_raises(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        session = await store.create_session(metadata={}, agent_id="brain")

        msg = SessionMessage(session_id="other-id", role="user", content="oops")
        with pytest.raises(ValueError, match="session_id"):
            await store.add_message(session.id, msg)

    asyncio.run(_run())


# ──────────────────────────────────────────────────────────────────────────────
# Artifacts
# ──────────────────────────────────────────────────────────────────────────────


def test_store_and_get_artifact(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        session = await store.create_session(metadata={}, agent_id="ghost")

        artifact = SessionArtifact(
            session_id=session.id,
            artifact_type="screenshot",
            name="captcha_01.png",
            content=b"\x89PNG\r\n\x1a\n",
            mime_type="image/png",
        )
        await store.store_artifact(session.id, artifact)

        fetched = await store.get_artifact(artifact.id)
        assert fetched is not None
        assert fetched.id == artifact.id
        assert fetched.name == "captcha_01.png"
        assert fetched.content == b"\x89PNG\r\n\x1a\n"
        assert fetched.mime_type == "image/png"
        assert fetched.artifact_type == "screenshot"

    asyncio.run(_run())


def test_get_artifact_returns_none_for_unknown(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        result = await store.get_artifact("nonexistent-artifact-id")
        assert result is None

    asyncio.run(_run())


def test_artifact_stored_as_bytes(tmp_path: Path) -> None:
    """Ensure binary content round-trips correctly."""

    async def _run() -> None:
        store = await fresh_store(tmp_path)
        session = await store.create_session(metadata={}, agent_id="brain")

        binary_data = bytes(range(256))
        artifact = SessionArtifact(
            session_id=session.id,
            artifact_type="data",
            name="raw.bin",
            content=binary_data,
            mime_type="application/octet-stream",
        )
        await store.store_artifact(session.id, artifact)
        fetched = await store.get_artifact(artifact.id)
        assert fetched is not None
        assert fetched.content == binary_data

    asyncio.run(_run())


# ──────────────────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────────────────


def test_cleanup_old_sessions(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)

        # Create one that looks old (manually insert with old created_at)
        old_session = await store.create_session(metadata={}, agent_id="brain")
        await store.update_session_state(old_session.id, SessionState.COMPLETED)

        # Backdate it by changing row directly
        async with store._connect() as db:
            old_ts = time.time() - (40 * 86_400)  # 40 days ago
            await db.execute(
                "UPDATE sessions SET created_at = ? WHERE id = ?",
                (old_ts, old_session.id),
            )
            await db.commit()

        # Create one recent session (active, should survive)
        _ = await store.create_session(metadata={}, agent_id="brain")

        deleted = await store.cleanup_old_sessions(older_than_days=30)
        assert deleted == 1

        all_sessions = await store.list_sessions()
        assert len(all_sessions) == 1  # only the recent one remains

    asyncio.run(_run())


def test_cleanup_skips_active_sessions(tmp_path: Path) -> None:
    """Active sessions are never deleted even if they are old."""

    async def _run() -> None:
        store = await fresh_store(tmp_path)
        s = await store.create_session(metadata={}, agent_id="brain")

        # Backdate it
        async with store._connect() as db:
            old_ts = time.time() - (90 * 86_400)
            await db.execute(
                "UPDATE sessions SET created_at = ? WHERE id = ?",
                (old_ts, s.id),
            )
            await db.commit()

        deleted = await store.cleanup_old_sessions(older_than_days=30)
        assert deleted == 0  # active sessions are protected

    asyncio.run(_run())


def test_cleanup_invalid_days_raises(tmp_path: Path) -> None:
    async def _run() -> None:
        store = await fresh_store(tmp_path)
        with pytest.raises(ValueError):
            await store.cleanup_old_sessions(older_than_days=0)

    asyncio.run(_run())


# ──────────────────────────────────────────────────────────────────────────────
# Migration Idempotency
# ──────────────────────────────────────────────────────────────────────────────


def test_initialize_is_idempotent(tmp_path: Path) -> None:
    async def _run() -> None:
        store = make_store(tmp_path)
        await store.initialize()
        await store.initialize()  # second call must not fail or duplicate tables

        session = await store.create_session(metadata={}, agent_id="brain")
        fetched = await store.get_session(session.id)
        assert fetched is not None

    asyncio.run(_run())


def test_data_persists_across_store_instances(tmp_path: Path) -> None:
    """Simulate process restart by creating a new SessionStore pointing to same DB."""

    async def _run() -> None:
        db_path = tmp_path / "persistent.db"

        store1 = SessionStore(db_path=db_path)
        await store1.initialize()
        session = await store1.create_session(metadata={"persisted": True}, agent_id="brain")
        session_id = session.id

        # Simulate restart
        store2 = SessionStore(db_path=db_path)
        await store2.initialize()
        fetched = await store2.get_session(session_id)
        assert fetched is not None
        assert fetched.metadata["persisted"] is True

    asyncio.run(_run())


# ──────────────────────────────────────────────────────────────────────────────
# Validation / Error Handling
# ──────────────────────────────────────────────────────────────────────────────


def test_session_model_rejects_empty_agent_id() -> None:
    try:
        Session(agent_id="   ")
        assert False, "Should have raised"
    except Exception as exc:
        assert "agent_id" in str(exc).lower() or "empty" in str(exc).lower()


def test_message_model_rejects_invalid_role() -> None:
    try:
        SessionMessage(session_id="sid", role="robot", content="hello")
        assert False, "Should have raised"
    except Exception as exc:
        assert "role" in str(exc).lower()


def test_artifact_model_rejects_invalid_type() -> None:
    try:
        SessionArtifact(
            session_id="sid",
            artifact_type="video",
            name="x.mp4",
            content=b"",
            mime_type="video/mp4",
        )
        assert False, "Should have raised"
    except Exception as exc:
        assert "artifact_type" in str(exc).lower()
