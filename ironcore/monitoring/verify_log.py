from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ironcore.monitoring.chain import verify_chain
from ironcore.monitoring.schemas import AuditLogEntry


def _load_entries(log_file: Path) -> list[AuditLogEntry]:
    entries: list[AuditLogEntry] = []
    with log_file.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entries.append(AuditLogEntry.model_validate_json(stripped))
            except Exception as exc:
                raise ValueError(f"invalid JSONL at line {line_number}: {exc}") from exc
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an IronCore audit log JSONL file.")
    parser.add_argument("--log-file", required=True, help="Path to audit_YYYY-MM-DD.jsonl")
    parser.add_argument(
        "--secret-key",
        help="Raw HMAC signing key. If omitted, --secret-key-env is used.",
    )
    parser.add_argument(
        "--secret-key-env",
        default="IRONCORE_AUDIT_HMAC_KEY",
        help="Environment variable containing the HMAC signing key.",
    )
    args = parser.parse_args(argv)

    signing_key = args.secret_key or os.environ.get(args.secret_key_env)
    if not signing_key:
        print(
            f"[ERROR] Missing signing key. Pass --secret-key or set {args.secret_key_env}.",
            file=sys.stderr,
        )
        return 2

    log_file = Path(args.log_file).expanduser()
    if not log_file.exists():
        print(f"[ERROR] Log file not found: {log_file}", file=sys.stderr)
        return 2

    try:
        entries = _load_entries(log_file)
        result = verify_chain(entries, signing_key)
    except Exception as exc:
        print(f"[ERROR] Verification failed: {exc}", file=sys.stderr)
        return 2

    if result.is_intact:
        print(f"[OK] {result.verified_entries} entries verified. Chain integrity: INTACT.")
        return 0

    print(
        f"[WARN] Entry #{result.broken_entry_seq}: {result.error}. "
        f"Verified before failure: {result.verified_entries}.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
