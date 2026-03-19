from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel

from ironcore.core.engine import Event, EventBus
from ironcore.monitoring.chain import GENESIS_HASH, compute_entry_hash
from ironcore.monitoring.schemas import AuditLogEntry
from ironcore.security.secrets_vault import SecretsVault

logger = logging.getLogger(__name__)

_REDACTED = "[REDACTED]"
_SENSITIVE_TOKENS = ("password", "api_key", "token", "secret")


class AuditLogger:
    """
    Persist every EventBus event to an append-only, tamper-evident JSONL log.

    The logger runs as a background task consuming EventBus.consume_all(). Each
    entry is chained with HMAC-SHA256 so retroactive modifications are detectable.
    """

    def __init__(
        self,
        event_bus: EventBus,
        vault: SecretsVault,
        log_dir: str | Path | None = None,
        signing_secret_name: str = "IRONCORE_AUDIT_HMAC_KEY",
        default_session_id: str = "unknown-session",
        default_agent: str = "ironcore",
    ) -> None:
        self._event_bus = event_bus
        self._vault = vault
        self._log_dir = Path(log_dir).expanduser() if log_dir else Path.home() / ".ironcore"
        self._signing_secret_name = signing_secret_name
        self._default_session_id = default_session_id
        self._default_agent = default_agent
        self._task: Optional[asyncio.Task[None]] = None
        self._active_day: Optional[str] = None
        self._active_file: Optional[Path] = None
        self._last_hash = GENESIS_HASH
        self._sequence = 0

    async def start(self) -> None:
        """Start consuming events in the background."""
        if self._task and not self._task.done():
            return
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._task = asyncio.create_task(self._run(), name="ironcore-audit-logger")
        logger.info("[AuditLogger] Started log_dir=%s", self._log_dir)

    async def stop(self) -> None:
        """Stop the background consumer gracefully."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            logger.info("[AuditLogger] Stopped.")
        finally:
            self._task = None

    async def _run(self) -> None:
        try:
            async for event in self._event_bus.consume_all():
                await self._write_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("[AuditLogger] Consumer crashed: %s", exc)
            raise

    async def _write_event(self, event: Event) -> AuditLogEntry:
        await self._rotate_if_needed()
        signing_key = self._vault.get(
            self._signing_secret_name,
            accessor="monitoring.audit_logger",
        )

        payload = self._normalize_payload(event.payload)
        redacted_payload = self._redact_payload(payload)

        self._sequence += 1
        entry_data = {
            "seq": self._sequence,
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "session_id": str(redacted_payload.get("session_id", self._default_session_id)),
            "payload": redacted_payload,
            "agent": str(redacted_payload.get("agent", self._default_agent)),
            "prev_hash": self._last_hash,
        }
        entry_hash = compute_entry_hash(
            self._last_hash,
            entry_data,
            signing_key,
        )
        entry = AuditLogEntry(**entry_data, entry_hash=entry_hash)
        self._append_jsonl(entry)
        self._last_hash = entry.entry_hash

        logger.debug(
            "[AuditLogger] Logged seq=%s event_type=%s file=%s",
            entry.seq,
            entry.event_type,
            self._active_file,
        )
        return entry

    async def _rotate_if_needed(self) -> None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if day == self._active_day and self._active_file is not None:
            return

        self._active_day = day
        self._active_file = self._log_dir / f"audit_{day}.jsonl"
        self._sequence = 0
        self._last_hash = GENESIS_HASH

        if not self._active_file.exists():
            logger.info("[AuditLogger] Rotated to new log file=%s", self._active_file)
            return

        last_line = ""
        with self._active_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    last_line = stripped

        if not last_line:
            logger.info("[AuditLogger] Rotated to empty existing log file=%s", self._active_file)
            return

        last_entry = AuditLogEntry.model_validate_json(last_line)
        self._sequence = last_entry.seq
        self._last_hash = last_entry.entry_hash
        logger.info(
            "[AuditLogger] Resumed file=%s seq=%s",
            self._active_file,
            self._sequence,
        )

    def _append_jsonl(self, entry: AuditLogEntry) -> None:
        if self._active_file is None:
            raise RuntimeError("Active log file is not initialized")
        with self._active_file.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json())
            handle.write("\n")

    def _normalize_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self._normalize_value(payload)
        if not isinstance(normalized, dict):
            return {"value": normalized}
        return normalized

    def _normalize_value(self, value: Any) -> Any:
        if isinstance(value, BaseModel):
            return {key: self._normalize_value(item) for key, item in value.model_dump(mode="json").items()}
        if is_dataclass(value):
            return {
                key: self._normalize_value(item)
                for key, item in value.__dict__.items()
            }
        if isinstance(value, dict):
            return {
                str(key): self._normalize_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self._normalize_value(item) for item in value]
        if isinstance(value, set):
            return [self._normalize_value(item) for item in sorted(value, key=repr)]
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    def _redact_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._redact_value(payload)

    def _redact_value(self, value: Any, key_name: str = "") -> Any:
        lowered_key = key_name.lower()
        if any(token in lowered_key for token in _SENSITIVE_TOKENS):
            return _REDACTED
        if isinstance(value, dict):
            return {
                key: self._redact_value(item, key)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact_value(item, key_name) for item in value]
        return value
