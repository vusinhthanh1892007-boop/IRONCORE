"""Phase 8 — Enterprise DLP Engine — Test Suite.

All tests are self-contained: no network calls, no Redis.
"""

from __future__ import annotations

import os
import re

import pytest

os.environ["IRONCORE_EDITION"] = "enterprise"

from ironcore.enterprise.dlp.engine import DLPAlert, DLPEngine, DLPThresholdError
from ironcore.enterprise.dlp.patterns import (
    COMPILED_PATTERNS,
    PIIMatch,
    PIIType,
    luhn_check,
)


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _engine(**kw) -> DLPEngine:
    return DLPEngine(**kw)


# ══════════════════════════════════════════════════════════════════════════════
#  TestLuhnCheck
# ══════════════════════════════════════════════════════════════════════════════

class TestLuhnCheck:
    def test_valid_visa(self) -> None:
        assert luhn_check("4111111111111111") is True

    def test_valid_mastercard(self) -> None:
        assert luhn_check("5500005555555559") is True

    def test_valid_amex(self) -> None:
        assert luhn_check("378282246310005") is True

    def test_invalid_card(self) -> None:
        assert luhn_check("4111111111111112") is False

    def test_all_zeros_valid_but_not_a_real_card(self) -> None:
        # All zeros satisfies Luhn (sum=0 divisible by 10) — the engine
        # relies on context (regex shape) to avoid false positives, not Luhn alone.
        assert luhn_check("0000000000000000") is True

    def test_too_short_invalid(self) -> None:
        assert luhn_check("123") is False

    def test_with_spaces_strips_and_validates(self) -> None:
        # luhn_check works on digit-only string — caller strips spaces
        assert luhn_check("4111111111111111") is True

    def test_non_digits_treated_as_invalid(self) -> None:
        # Non-digit characters yield wrong length → False
        assert luhn_check("abcdef") is False


# ══════════════════════════════════════════════════════════════════════════════
#  TestPIIPatterns  (raw regex only, no Luhn gate)
# ══════════════════════════════════════════════════════════════════════════════

class TestPIIPatterns:
    def test_email_pattern(self) -> None:
        p = COMPILED_PATTERNS[PIIType.EMAIL]
        assert p.search("user@example.com")
        assert p.search("user.name+tag@sub.domain.org")
        assert not p.search("not-an-email")

    def test_phone_vn_pattern(self) -> None:
        p = COMPILED_PATTERNS[PIIType.PHONE_VN]
        assert p.search("0912345678")
        assert p.search("0312345678")
        assert not p.search("0212345678")  # 02x — landline, not matched
        assert not p.search("123456789")   # no leading 0

    def test_national_id_pattern(self) -> None:
        p = COMPILED_PATTERNS[PIIType.NATIONAL_ID_VN]
        assert p.search("012345678901")     # 12 digits
        assert not p.search("12345678901")  # 11 digits

    def test_passport_vn_pattern(self) -> None:
        p = COMPILED_PATTERNS[PIIType.PASSPORT_VN]
        assert p.search("B1234567")
        assert not p.search("A1234567")   # must start with B
        assert not p.search("B123456")    # only 6 digits

    def test_jwt_pattern(self) -> None:
        p = COMPILED_PATTERNS[PIIType.JWT_TOKEN]
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.abc123def456ghi789"
        assert p.search(jwt)

    def test_ip_address_pattern(self) -> None:
        p = COMPILED_PATTERNS[PIIType.IP_ADDRESS]
        assert p.search("192.168.1.1")
        assert p.search("10.0.0.1")
        assert not p.search("256.256.256.256")

    def test_date_of_birth_pattern(self) -> None:
        p = COMPILED_PATTERNS[PIIType.DATE_OF_BIRTH]
        assert p.search("01/01/1990")
        assert p.search("31-12-2000")
        assert not p.search("1990/01/01")  # wrong order


# ══════════════════════════════════════════════════════════════════════════════
#  TestDLPEngineScan
# ══════════════════════════════════════════════════════════════════════════════

class TestDLPEngineScan:
    def test_detects_valid_visa_card(self) -> None:
        e = _engine()
        matches = e.scan("My card number is 4111111111111111.")
        cc = [m for m in matches if m.pii_type == PIIType.CREDIT_CARD]
        assert len(cc) == 1
        assert cc[0].original == "4111111111111111"

    def test_does_not_flag_luhn_invalid_card(self) -> None:
        e = _engine()
        # One digit wrong — fails Luhn
        matches = e.scan("Invalid card 4111111111111112 here.")
        cc = [m for m in matches if m.pii_type == PIIType.CREDIT_CARD]
        assert len(cc) == 0

    def test_detects_mastercard(self) -> None:
        e = _engine()
        matches = e.scan("5500005555555559")
        assert any(m.pii_type == PIIType.CREDIT_CARD for m in matches)

    def test_detects_email(self) -> None:
        e = _engine()
        matches = e.scan("Contact alice@example.com for support.")
        assert any(m.pii_type == PIIType.EMAIL and m.original == "alice@example.com" for m in matches)

    def test_detects_phone_vn(self) -> None:
        e = _engine()
        matches = e.scan("Call 0912345678 now.")
        assert any(m.pii_type == PIIType.PHONE_VN for m in matches)

    def test_detects_national_id(self) -> None:
        e = _engine()
        matches = e.scan("CCCD: 012345678901")
        assert any(m.pii_type == PIIType.NATIONAL_ID_VN for m in matches)

    def test_detects_passport_vn(self) -> None:
        e = _engine()
        matches = e.scan("Passport B1234567 issued.")
        assert any(m.pii_type == PIIType.PASSPORT_VN for m in matches)

    def test_detects_jwt_token(self) -> None:
        e = _engine()
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.abc123def456ghi789"
        matches = e.scan(f"Token: {jwt}")
        assert any(m.pii_type == PIIType.JWT_TOKEN for m in matches)

    def test_detects_ip_address(self) -> None:
        e = _engine()
        matches = e.scan("Client from 192.168.1.100.")
        assert any(m.pii_type == PIIType.IP_ADDRESS for m in matches)

    def test_detects_date_of_birth(self) -> None:
        e = _engine()
        matches = e.scan("Born: 15/08/1990.")
        assert any(m.pii_type == PIIType.DATE_OF_BIRTH for m in matches)

    def test_multiple_pii_in_one_text(self) -> None:
        e = _engine()
        text = "Name: alice@example.com phone: 0912345678"
        matches = e.scan(text)
        types = {m.pii_type for m in matches}
        assert PIIType.EMAIL in types
        assert PIIType.PHONE_VN in types

    def test_no_pii_returns_empty(self) -> None:
        e = _engine()
        assert e.scan("Hello, this is plain text.") == []

    def test_disabled_type_not_detected(self) -> None:
        e = DLPEngine(enabled_types=[PIIType.EMAIL])
        matches = e.scan("Call 0912345678 or email alice@example.com")
        types = {m.pii_type for m in matches}
        assert PIIType.EMAIL in types
        assert PIIType.PHONE_VN not in types

    def test_matches_sorted_by_start(self) -> None:
        e = _engine()
        text = "email@example.com and 0987654321"
        matches = e.scan(text)
        starts = [m.start for m in matches]
        assert starts == sorted(starts)


# ══════════════════════════════════════════════════════════════════════════════
#  TestDLPEngineMask
# ══════════════════════════════════════════════════════════════════════════════

class TestDLPEngineMask:
    def test_mask_visa_keeps_last_4(self) -> None:
        e = _engine()
        result = e.mask("Card: 4111111111111111")
        assert "1111" in result
        assert "4111111111" not in result

    def test_mask_email_hides_local(self) -> None:
        e = _engine()
        result = e.mask("Contact alice@example.com")
        assert "alice" not in result
        # Domain is also partially masked: a****@e******.com
        assert "@e" in result
        assert ".com" in result

    def test_mask_phone_keeps_prefix_and_suffix(self) -> None:
        e = _engine()
        result = e.mask("Phone: 0912345678")
        assert result.startswith("Phone: 091")
        assert result.endswith("78")

    def test_mask_national_id_keeps_last_4(self) -> None:
        e = _engine()
        result = e.mask("ID: 012345678901")
        assert "8901" in result
        assert "012345" not in result

    def test_mask_jwt_shows_prefix_and_suffix(self) -> None:
        e = _engine()
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.abc123def456ghi789"
        result = e.mask(f"token={jwt}")
        assert "eyJhbG" in result

    def test_mask_ip_hides_last_two_octets(self) -> None:
        e = _engine()
        result = e.mask("IP: 192.168.1.100")
        assert "192.168" in result
        # Last two octets masked
        assert "1.100" not in result

    def test_mask_no_pii_unchanged(self) -> None:
        e = _engine()
        text = "No sensitive data here."
        assert e.mask(text) == text

    def test_mask_custom_char(self) -> None:
        e = DLPEngine(mask_char="#")
        result = e.mask("Email: alice@example.com")
        assert "#" in result

    def test_mask_does_not_expose_pii_in_result(self) -> None:
        e = _engine()
        result = e.mask("4111111111111111 and alice@example.com")
        assert "41111111111" not in result
        assert "alice" not in result


# ══════════════════════════════════════════════════════════════════════════════
#  TestDLPEngineTokenize
# ══════════════════════════════════════════════════════════════════════════════

class TestDLPEngineTokenize:
    def test_tokenize_returns_token_and_map(self) -> None:
        e = _engine()
        text = "email: alice@example.com"
        result, token_map = e.tokenize(text)
        assert "alice@example.com" not in result
        assert len(token_map) == 1
        assert "alice@example.com" in token_map.values()

    def test_tokenize_token_format(self) -> None:
        e = _engine()
        _, token_map = e.tokenize("Call 0912345678")
        token = list(token_map.keys())[0]
        assert token.startswith("[") and token.endswith("]")

    def test_detokenize_restores_original(self) -> None:
        e = _engine()
        text = "Card: 4111111111111111"
        tokenised, token_map = e.tokenize(text)
        restored = e.detokenize(tokenised, token_map)
        assert "4111111111111111" in restored

    def test_tokenize_empty_text_no_map(self) -> None:
        e = _engine()
        result, token_map = e.tokenize("No PII here.")
        assert result == "No PII here."
        assert token_map == {}

    def test_detokenize_unknown_tokens_unchanged(self) -> None:
        e = _engine()
        text = "Hello [UNKNOWN_1234]"
        result = e.detokenize(text, {})
        assert result == text

    def test_tokenize_multiple_pii_all_mapped(self) -> None:
        e = _engine()
        text = "email alice@example.com phone 0912345678"
        _, token_map = e.tokenize(text)
        values = set(token_map.values())
        assert "alice@example.com" in values
        assert "0912345678" in values

    def test_tokenize_roundtrip_exact(self) -> None:
        e = _engine()
        original = "CCCD: 012345678901 phone: 0987654321"
        tokenised, token_map = e.tokenize(original)
        restored = e.detokenize(tokenised, token_map)
        assert restored == original

    def test_tokenize_preserves_surrounding_text(self) -> None:
        e = _engine()
        text = "Before 0912345678 after"
        tokenised, _ = e.tokenize(text)
        assert tokenised.startswith("Before ")
        assert tokenised.endswith(" after")


# ══════════════════════════════════════════════════════════════════════════════
#  TestDLPEngineAuditScan
# ══════════════════════════════════════════════════════════════════════════════

class TestDLPEngineAuditScan:
    def test_audit_scan_no_pii_returns_none(self) -> None:
        e = _engine()
        result = e.audit_scan("Plain text.", source="test")
        assert result is None

    def test_audit_scan_pii_returns_alert(self) -> None:
        e = _engine()
        result = e.audit_scan("Card: 4111111111111111", source="llm_prompt")
        assert isinstance(result, DLPAlert)
        assert result.count >= 1
        assert result.source == "llm_prompt"

    def test_audit_scan_alert_count_matches(self) -> None:
        e = _engine()
        text = "emails: alice@example.com bob@example.com"
        result = e.audit_scan(text)
        assert result is not None
        assert result.count >= 2

    def test_audit_scan_above_threshold_raises(self) -> None:
        e = DLPEngine(alert_threshold=3)
        # Build a text with 4 phone numbers
        phones = " ".join(f"091{i:07d}" for i in range(4))
        # Ensure phones are Luhn-free (they are — phones don't go through Luhn)
        # Check some are valid phone patterns
        with pytest.raises(DLPThresholdError) as exc_info:
            e.audit_scan(phones)
        assert exc_info.value.count >= 4

    def test_audit_scan_does_not_log_raw_pii(self, caplog) -> None:
        import logging
        e = _engine()
        with caplog.at_level(logging.WARNING, logger="ironcore.enterprise.dlp.engine"):
            e.audit_scan("Call 0912345678 or 0987654321", source="log")
        # Verify the raw phone numbers are NOT in log records
        for record in caplog.records:
            assert "0912345678" not in record.message
            assert "0987654321" not in record.message

    def test_dlp_threshold_error_has_count(self) -> None:
        e = DLPEngine(alert_threshold=1)
        text = "alice@example.com bob@example.com"
        with pytest.raises(DLPThresholdError) as exc_info:
            e.audit_scan(text)
        assert exc_info.value.threshold == 1


# ══════════════════════════════════════════════════════════════════════════════
#  TestDLPEngineEdition
# ══════════════════════════════════════════════════════════════════════════════

class TestDLPEngineEdition:
    def test_community_edition_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_EDITION", "community")
        with pytest.raises(RuntimeError, match="Enterprise"):
            DLPEngine()
        monkeypatch.setenv("IRONCORE_EDITION", "enterprise")  # restore

    def test_from_env_reads_mask_char(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_DLP_MASK_CHAR", "#")
        monkeypatch.setenv("IRONCORE_DLP_TOKENIZE", "true")
        e = DLPEngine.from_env()
        assert e._mask_char == "#"

    def test_from_env_reads_threshold(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_DLP_ALERT_THRESHOLD", "50")
        e = DLPEngine.from_env()
        assert e._alert_threshold == 50

    def test_from_env_reads_types(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_DLP_TYPES", "email,phone_vn")
        e = DLPEngine.from_env()
        assert PIIType.EMAIL in e._enabled
        assert PIIType.PHONE_VN in e._enabled
        assert PIIType.CREDIT_CARD not in e._enabled


# ══════════════════════════════════════════════════════════════════════════════
#  TestDLPAlert model
# ══════════════════════════════════════════════════════════════════════════════

class TestDLPAlert:
    def test_alert_fields(self) -> None:
        import time
        alert = DLPAlert(
            timestamp=time.time(),
            pii_type="credit_card",
            source="llm_prompt",
            session_id="sess-abc",
            count=3,
        )
        assert alert.pii_type == "credit_card"
        assert alert.count == 3
        assert "4111" not in alert.model_dump_json()  # No raw PII


# ══════════════════════════════════════════════════════════════════════════════
#  TestDLPIntegration
# ══════════════════════════════════════════════════════════════════════════════

class TestDLPIntegration:
    def test_full_pipeline_tokenize_then_detokenize(self) -> None:
        """Simulate LLM pipeline: tokenize → pretend LLM echoes token → detokenize."""
        e = _engine()
        user_input = "Analyse card 4111111111111111 and email alice@example.com"
        tokenised, token_map = e.tokenize(user_input)

        # Simulate LLM echoes tokens back in its response
        llm_response = f"The card {list(token_map.keys())[0]} appears valid."
        restored = e.detokenize(llm_response, token_map)

        assert "4111111111111111" in restored or "alice@example.com" in restored

    def test_mask_used_for_logging(self) -> None:
        """Verify masking is appropriate for logging (no raw PII)."""
        e = _engine()
        raw_log = '{"user": "alice@example.com", "card": "4111111111111111"}'
        safe_log = e.mask(raw_log)
        assert "alice@example.com" not in safe_log
        assert "4111111111111111" not in safe_log
        # Ensure structural content preserved
        assert "user" in safe_log
        assert "card" in safe_log

    def test_formatted_card_with_dashes_detected(self) -> None:
        e = _engine()
        matches = e.scan("Card: 4111-1111-1111-1111")
        # After stripping dashes, this is 4111111111111111 = valid Luhn
        cc = [m for m in matches if m.pii_type == PIIType.CREDIT_CARD]
        assert len(cc) == 1

    def test_amex_card_detected(self) -> None:
        e = _engine()
        matches = e.scan("378282246310005")
        cc = [m for m in matches if m.pii_type == PIIType.CREDIT_CARD]
        assert len(cc) == 1

    def test_scan_performance_large_text(self) -> None:
        """10 000 character text should scan in < 100 ms (very generous bound)."""
        import time
        e = _engine()
        # Build a text with some PII scattered throughout
        chunk = "Lorem ipsum alice@test.com dolor 0912345678 sit amet. " * 100
        text = chunk[:10_000]
        t0 = time.monotonic()
        e.scan(text)
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert elapsed_ms < 100, f"Scan took {elapsed_ms:.1f} ms — too slow"
