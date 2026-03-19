from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from ironcore.core.engine import Event, EventBus
from ironcore.monitoring.audit_logger import AuditLogger
from ironcore.monitoring.chain import verify_chain
from ironcore.monitoring.schemas import AuditLogEntry
from ironcore.security.policy_engine import BaseRule, DangerousArgPatternRule, PolicyEngine, PolicyVerdict, RateLimitRule
from ironcore.security.secrets_vault import SecretsVault


def test_vault_encrypt_decrypt_roundtrip(vault: SecretsVault) -> None:
    vault.store("OPENAI_SESSION", "secret-value")

    assert vault.get("OPENAI_SESSION", accessor="tests") == "secret-value"


def test_expired_secret_raises(vault: SecretsVault) -> None:
    vault.store("TEMP_SECRET", "soon-expired", ttl_seconds=0.01)
    time.sleep(0.02)

    with pytest.raises(PermissionError):
        vault.get("TEMP_SECRET", accessor="tests")


def test_injection_pattern_detected(policy_engine: PolicyEngine) -> None:
    result = policy_engine.evaluate(
        tool_name="read_file",
        args={"path": "../etc/passwd"},
        context={"risk_level": "LOW"},
    )

    assert result.verdict == PolicyVerdict.DENY


def test_rate_limit_enforced() -> None:
    rule = RateLimitRule({"web_search": (1, 60.0)})

    assert rule.evaluate("web_search", {}, {}).verdict == PolicyVerdict.ALLOW
    assert rule.evaluate("web_search", {}, {}).verdict == PolicyVerdict.DENY


def test_chain_deny_short_circuits() -> None:
    calls = {"count": 0}

    class CountingRule(BaseRule):
        @property
        def name(self) -> str:
            return "counting"

        def evaluate(self, tool_name, args, context):
            del tool_name, args, context
            calls["count"] += 1
            return DangerousArgPatternRule().evaluate("noop", {}, {})

    engine = PolicyEngine()
    engine.add_rule(DangerousArgPatternRule())
    engine.add_rule(RateLimitRule({}))
    engine.add_rule(CountingRule())

    result = engine.evaluate(
        tool_name="read_file",
        args={"path": "../etc/passwd"},
        context={},
    )

    assert result.verdict == PolicyVerdict.DENY
    assert calls["count"] == 0


@pytest.mark.asyncio
async def test_audit_chain_integrity(vault: SecretsVault, tmp_path: Path) -> None:
    event_bus = EventBus()
    logger = AuditLogger(event_bus=event_bus, vault=vault, log_dir=tmp_path)

    await logger.start()
    await event_bus.publish(
        Event(
            event_type="tool.executed",
            payload={"session_id": "s-1", "agent": "architect", "result": "ok"},
        )
    )
    await asyncio.sleep(0.05)
    await logger.stop()

    log_file = next(tmp_path.glob("audit_*.jsonl"))
    entries = [
        AuditLogEntry.model_validate_json(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    result = verify_chain(entries, "audit-signing-secret")
    assert result.is_intact is True


def test_audit_chain_detects_tampering(vault: SecretsVault, tmp_path: Path) -> None:
    async def scenario() -> list[AuditLogEntry]:
        event_bus = EventBus()
        logger = AuditLogger(event_bus=event_bus, vault=vault, log_dir=tmp_path)
        await logger.start()
        await event_bus.publish(
            Event(
                event_type="tool.executed",
                payload={"session_id": "s-1", "agent": "architect", "token": "hidden"},
            )
        )
        await asyncio.sleep(0.05)
        await logger.stop()

        log_file = next(tmp_path.glob("audit_*.jsonl"))
        return [
            AuditLogEntry.model_validate(json.loads(line))
            for line in log_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    entries = asyncio.run(scenario())
    tampered = entries[0].model_copy(update={"entry_hash": "bad"})

    result = verify_chain([tampered], "audit-signing-secret")
    assert result.is_intact is False
    assert result.error == "entry_hash_mismatch"
