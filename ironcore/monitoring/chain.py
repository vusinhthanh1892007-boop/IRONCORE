from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Iterable, Mapping

from ironcore.monitoring.schemas import AuditLogEntry, ChainVerificationResult

GENESIS_STRING = "IRONCORE_AUDIT_LOG_GENESIS_V1"
GENESIS_HASH = hashlib.sha256(GENESIS_STRING.encode("utf-8")).hexdigest()


def _canonical_json(entry_data: Mapping[str, Any]) -> str:
    return json.dumps(
        entry_data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def compute_entry_hash(
    prev_hash: str,
    entry_data: Mapping[str, Any],
    secret_key: str,
) -> str:
    payload = f"{prev_hash}{_canonical_json(entry_data)}".encode("utf-8")
    return hmac.new(
        secret_key.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()


def verify_chain(
    entries: Iterable[AuditLogEntry],
    secret_key: str,
) -> ChainVerificationResult:
    previous_hash = GENESIS_HASH
    verified_entries = 0

    for entry in entries:
        if entry.prev_hash != previous_hash:
            return ChainVerificationResult(
                is_intact=False,
                verified_entries=verified_entries,
                broken_entry_seq=entry.seq,
                expected_prev_hash=previous_hash,
                actual_prev_hash=entry.prev_hash,
                error="broken_chain_link",
            )

        entry_data = entry.model_dump(exclude={"entry_hash"})
        expected_hash = compute_entry_hash(entry.prev_hash, entry_data, secret_key)
        if not hmac.compare_digest(expected_hash, entry.entry_hash):
            return ChainVerificationResult(
                is_intact=False,
                verified_entries=verified_entries,
                broken_entry_seq=entry.seq,
                expected_prev_hash=previous_hash,
                actual_prev_hash=entry.prev_hash,
                expected_entry_hash=expected_hash,
                actual_entry_hash=entry.entry_hash,
                error="entry_hash_mismatch",
            )

        previous_hash = entry.entry_hash
        verified_entries += 1

    return ChainVerificationResult(
        is_intact=True,
        verified_entries=verified_entries,
    )
