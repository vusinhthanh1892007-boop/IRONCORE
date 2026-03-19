import asyncio
import json

from ironcore.core.engine import Event, EventBus
from ironcore.monitoring.audit_logger import AuditLogger
from ironcore.monitoring.chain import GENESIS_HASH, compute_entry_hash, verify_chain
from ironcore.monitoring.schemas import AuditLogEntry


class FakeVault:
    def __init__(self, secret: str = "test-signing-key") -> None:
        self.secret = secret
        self.accesses: list[tuple[str, str]] = []

    def get(self, name: str, accessor: str = "unknown") -> str:
        self.accesses.append((name, accessor))
        return self.secret


def test_compute_entry_hash_is_deterministic() -> None:
    entry = {
        "seq": 1,
        "timestamp": 123.0,
        "event_type": "tool.executed",
        "session_id": "session-1",
        "payload": {"ok": True},
        "agent": "architect",
        "prev_hash": GENESIS_HASH,
    }

    first = compute_entry_hash(GENESIS_HASH, entry, "secret")
    second = compute_entry_hash(GENESIS_HASH, entry, "secret")

    assert first == second


def test_verify_chain_detects_tampering() -> None:
    base = {
        "seq": 1,
        "timestamp": 100.0,
        "event_type": "agent.started",
        "session_id": "s1",
        "payload": {"agent": "architect"},
        "agent": "architect",
        "prev_hash": GENESIS_HASH,
    }
    first_hash = compute_entry_hash(GENESIS_HASH, base, "secret")
    entry = AuditLogEntry(**base, entry_hash=first_hash)

    result_ok = verify_chain([entry], "secret")
    assert result_ok.is_intact is True

    tampered = entry.model_copy(update={"entry_hash": "bad"})
    result_bad = verify_chain([tampered], "secret")
    assert result_bad.is_intact is False
    assert result_bad.error == "entry_hash_mismatch"


def test_audit_logger_redacts_sensitive_keys(tmp_path) -> None:
    logger = AuditLogger(
        event_bus=EventBus(),
        vault=FakeVault(),
        log_dir=tmp_path,
    )

    payload = {
        "session_id": "s-1",
        "agent": "architect",
        "token": "abc",
        "nested": {"api_key": "secret-value", "safe": "ok"},
    }

    redacted = logger._redact_payload(payload)
    assert redacted["token"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert redacted["nested"]["safe"] == "ok"


def test_audit_logger_writes_chained_jsonl(tmp_path) -> None:
    async def scenario() -> None:
        event_bus = EventBus()
        fake_vault = FakeVault()
        audit_logger = AuditLogger(
            event_bus=event_bus,
            vault=fake_vault,
            log_dir=tmp_path,
            default_session_id="fallback-session",
            default_agent="fallback-agent",
        )

        await audit_logger.start()
        await event_bus.publish(Event(
            event_type="action.completed",
            payload={
                "session_id": "session-42",
                "agent": "architect",
                "token": "should-hide",
                "result": "ok",
            },
        ))
        await asyncio.sleep(0.05)
        await audit_logger.stop()

        log_files = list(tmp_path.glob("audit_*.jsonl"))
        assert len(log_files) == 1

        lines = log_files[0].read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = AuditLogEntry.model_validate(json.loads(lines[0]))
        assert entry.payload["token"] == "[REDACTED]"
        assert fake_vault.accesses[0][1] == "monitoring.audit_logger"

        result = verify_chain([entry], fake_vault.secret)
        assert result.is_intact is True

    asyncio.run(scenario())
