"""Phase 11 — Enterprise SIEM/SOC Integration — Test Suite.

All tests are self-contained: no real Splunk/Datadog/Syslog required.
Transport layer is stubbed with AsyncMock.
"""

from __future__ import annotations

import asyncio
import os
import time
import tempfile
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ["IRONCORE_EDITION"] = "enterprise"

from ironcore.enterprise.siem.cef_formatter import (
    CEFFormatter,
    CEFSeverity,
    _escape_extension,
    _escape_header,
    _payload_summary,
)
from ironcore.enterprise.siem.streamer import SIEMStreamer
from ironcore.enterprise.siem.transports import (
    BaseSIEMTransport,
    DatadogTransport,
    SplunkHECTransport,
    SyslogTCPTransport,
)
from ironcore.monitoring.schemas import AuditLogEntry


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _entry(
    event_type: str = "action_executed",
    session_id: str = "sess-001",
    agent: str = "ironcore",
    seq: int = 1,
    payload: dict = None,
) -> AuditLogEntry:
    return AuditLogEntry(
        seq=seq,
        timestamp=1700000000.0,
        event_type=event_type,
        session_id=session_id,
        payload=payload or {"action": "test"},
        agent=agent,
        prev_hash="aabbccdd",
        entry_hash="11223344",
    )


def _make_streamer(
    transports: list = None,
    dlp_engine=None,
    failsafe_path: str = "/tmp/ironcore-failsafe-test.log",
    flush_interval: float = 0.05,
) -> SIEMStreamer:
    formatter = CEFFormatter(hostname="test-host")
    if transports is None:
        transports = [SplunkHECTransport(url="https://splunk.test:8088", hec_token="tok")]
    return SIEMStreamer(
        transports=transports,
        formatter=formatter,
        dlp_engine=dlp_engine,
        buffer_size=100,
        flush_interval=flush_interval,
        failsafe_path=failsafe_path,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  TestCEFEscaping
# ══════════════════════════════════════════════════════════════════════════════

class TestCEFEscaping:
    def test_escape_header_pipe(self) -> None:
        assert "\\|" in _escape_header("foo|bar")

    def test_escape_header_backslash(self) -> None:
        assert "\\\\" in _escape_header("foo\\bar")

    def test_escape_header_no_modification_for_normal(self) -> None:
        assert _escape_header("IronCore") == "IronCore"

    def test_escape_extension_equals(self) -> None:
        assert "\\=" in _escape_extension("key=value")

    def test_escape_extension_backslash(self) -> None:
        assert "\\\\" in _escape_extension("a\\b")

    def test_escape_extension_newline(self) -> None:
        assert "\\n" in _escape_extension("line1\nline2")

    def test_escape_extension_carriage_return(self) -> None:
        assert "\\r" in _escape_extension("line1\rline2")


# ══════════════════════════════════════════════════════════════════════════════
#  TestPayloadSummary
# ══════════════════════════════════════════════════════════════════════════════

class TestPayloadSummary:
    def test_short_payload_no_truncation(self) -> None:
        result = _payload_summary({"action": "test"})
        assert "test" in result

    def test_long_payload_truncated(self) -> None:
        big = {"key": "x" * 300}
        result = _payload_summary(big, max_chars=50)
        assert result.endswith("...")

    def test_newlines_removed(self) -> None:
        result = _payload_summary({"key": "a\nb"})
        assert "\n" not in result


# ══════════════════════════════════════════════════════════════════════════════
#  TestCEFSeverity
# ══════════════════════════════════════════════════════════════════════════════

class TestCEFSeverity:
    def test_values(self) -> None:
        assert CEFSeverity.UNKNOWN == 0
        assert CEFSeverity.LOW == 3
        assert CEFSeverity.MEDIUM == 5
        assert CEFSeverity.HIGH == 7
        assert CEFSeverity.CRITICAL == 10

    def test_is_int(self) -> None:
        assert isinstance(CEFSeverity.HIGH, int)


# ══════════════════════════════════════════════════════════════════════════════
#  TestCEFFormatter
# ══════════════════════════════════════════════════════════════════════════════

class TestCEFFormatter:
    def test_format_starts_with_cef0(self) -> None:
        f = CEFFormatter(hostname="test")
        line = f.format(_entry())
        assert line.startswith("CEF:0|")

    def test_format_has_8_pipe_separated_header_fields(self) -> None:
        f = CEFFormatter()
        line = f.format(_entry())
        # CEF:0|Vendor|Product|Version|SigID|Name|Sev|Extension
        # Count unescaped pipes: first 7 pipes separate 8 fields
        parts = line.split("|")
        assert len(parts) >= 8

    def test_format_vendor_product_version(self) -> None:
        f = CEFFormatter()
        line = f.format(_entry())
        assert "IronCore" in line
        assert "IronCore-AI-Platform" in line
        assert "2.0" in line

    def test_format_known_event_type_uses_correct_sig_id(self) -> None:
        f = CEFFormatter()
        line = f.format(_entry("action_executed"))
        assert "|100|" in line

    def test_format_critical_action_sig_id(self) -> None:
        f = CEFFormatter()
        line = f.format(_entry("critical_action"))
        assert "|200|" in line

    def test_format_dlp_event_sig_id(self) -> None:
        f = CEFFormatter()
        line = f.format(_entry("dlp_pii_detected"))
        assert "|500|" in line

    def test_format_auth_failure_high_severity(self) -> None:
        f = CEFFormatter()
        line = f.format(_entry("auth_failure"))
        # Severity 7 = HIGH
        assert "|7|" in line

    def test_format_airgap_violation_critical(self) -> None:
        f = CEFFormatter()
        line = f.format(_entry("airgap_violation"))
        assert "|10|" in line

    def test_format_unknown_event_uses_999(self) -> None:
        f = CEFFormatter()
        line = f.format(_entry("totally_unknown_event"))
        assert "|999|" in line

    def test_format_extension_contains_session_id(self) -> None:
        f = CEFFormatter()
        line = f.format(_entry(session_id="sess-xyz"))
        assert "sess-xyz" in line

    def test_format_extension_contains_rt(self) -> None:
        f = CEFFormatter()
        line = f.format(_entry())
        assert "rt=" in line

    def test_format_extension_contains_act(self) -> None:
        f = CEFFormatter()
        line = f.format(_entry("policy_violation"))
        assert "act=policy_violation" in line

    def test_format_no_trailing_newline(self) -> None:
        f = CEFFormatter()
        line = f.format(_entry())
        assert not line.endswith("\n")

    def test_format_single_line(self) -> None:
        f = CEFFormatter()
        line = f.format(_entry())
        assert "\n" not in line

    def test_format_hostname_in_extension(self) -> None:
        f = CEFFormatter(hostname="vault-node-1")
        line = f.format(_entry())
        assert "vault-node-1" in line

    def test_format_batch_returns_list(self) -> None:
        f = CEFFormatter()
        entries = [_entry(seq=i) for i in range(1, 6)]
        lines = f.format_batch(entries)
        assert len(lines) == 5

    def test_format_batch_empty_input(self) -> None:
        f = CEFFormatter()
        assert f.format_batch([]) == []

    def test_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_SIEM_HOSTNAME", "prod-siem-host")
        f = CEFFormatter.from_env()
        line = f.format(_entry())
        assert "prod-siem-host" in line


# ══════════════════════════════════════════════════════════════════════════════
#  TestCEFFormatterEditionGuard
# ══════════════════════════════════════════════════════════════════════════════

class TestCEFFormatterEditionGuard:
    def test_community_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_EDITION", "community")
        with pytest.raises(RuntimeError, match="Enterprise"):
            CEFFormatter()
        monkeypatch.setenv("IRONCORE_EDITION", "enterprise")


# ══════════════════════════════════════════════════════════════════════════════
#  TestSplunkHECTransport
# ══════════════════════════════════════════════════════════════════════════════

class TestSplunkHECTransport:
    @pytest.mark.asyncio
    async def test_send_stub_no_error(self) -> None:
        t = SplunkHECTransport(url="https://splunk.test", hec_token="tok")
        await t.send(["CEF:0|test"])  # Should not raise

    @pytest.mark.asyncio
    async def test_send_stub_empty_no_error(self) -> None:
        t = SplunkHECTransport(url="https://splunk.test", hec_token="tok")
        await t.send([])

    @pytest.mark.asyncio
    async def test_health_check_stub_returns_true(self) -> None:
        t = SplunkHECTransport(url="https://splunk.test", hec_token="tok")
        assert await t.health_check() is True

    @pytest.mark.asyncio
    async def test_send_with_http_client(self) -> None:
        resp = MagicMock()
        resp.json = lambda: {"text": "Success", "code": 0}
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=resp)

        t = SplunkHECTransport(url="https://splunk.test", hec_token="tok", http_client=mock_http)
        await t.send(["CEF:0|test line"])
        mock_http.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_rejected_by_splunk_raises(self) -> None:
        resp = MagicMock()
        resp.json = lambda: {"text": "Invalid token", "code": 4}
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=resp)

        t = SplunkHECTransport(url="https://splunk.test", hec_token="bad-tok", http_client=mock_http)
        with pytest.raises(RuntimeError, match="Rejected"):
            await t.send(["CEF:0|test"])

    @pytest.mark.asyncio
    async def test_health_check_with_http_ok(self) -> None:
        resp = MagicMock()
        resp.json = lambda: {"text": "HEC is healthy", "code": 17}
        mock_http = MagicMock()
        mock_http.get = AsyncMock(return_value=resp)

        t = SplunkHECTransport(url="https://splunk.test", hec_token="tok", http_client=mock_http)
        assert await t.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_with_http_fail(self) -> None:
        mock_http = MagicMock()
        mock_http.get = AsyncMock(side_effect=ConnectionError("refused"))

        t = SplunkHECTransport(url="https://splunk.test", hec_token="tok", http_client=mock_http)
        assert await t.health_check() is False

    def test_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_SPLUNK_HEC_URL", "https://splunk.mybank.com:8088")
        monkeypatch.setenv("IRONCORE_SPLUNK_HEC_TOKEN", "tok123")
        monkeypatch.setenv("IRONCORE_SPLUNK_INDEX", "ai-events")
        t = SplunkHECTransport.from_env()
        assert t._url == "https://splunk.mybank.com:8088"
        assert t._hec_token == "tok123"
        assert t._index == "ai-events"

    @pytest.mark.asyncio
    async def test_send_batches_large_payloads(self) -> None:
        """250 events with batch_size=100 should make 3 POSTs."""
        resp = MagicMock()
        resp.json = lambda: {"code": 0}
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=resp)

        t = SplunkHECTransport(
            url="https://splunk.test", hec_token="tok",
            batch_size=100, http_client=mock_http
        )
        await t.send([f"CEF:0|event-{i}" for i in range(250)])
        assert mock_http.post.await_count == 3


# ══════════════════════════════════════════════════════════════════════════════
#  TestSyslogTCPTransport
# ══════════════════════════════════════════════════════════════════════════════

class TestSyslogTCPTransport:
    @pytest.mark.asyncio
    async def test_send_stub_no_error(self) -> None:
        t = SyslogTCPTransport(host="syslog.test", port=514)
        await t.send(["CEF:0|test"])

    @pytest.mark.asyncio
    async def test_health_check_stub_returns_true(self) -> None:
        t = SyslogTCPTransport(host="syslog.test")
        assert await t.health_check() is True

    def test_wrap_syslog_format(self) -> None:
        t = SyslogTCPTransport(host="syslog.test")
        raw = t._wrap_syslog("CEF:0|IronCore|test")
        decoded = raw.decode("utf-8")
        assert decoded.startswith("<13>")  # priority
        assert "CEF:0|IronCore|test" in decoded
        assert decoded.endswith("\n")

    @pytest.mark.asyncio
    async def test_send_with_socket_factory(self) -> None:
        writer = MagicMock()
        writer.write = MagicMock()
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        async def mock_socket_factory(host, port):
            return MagicMock(), writer

        t = SyslogTCPTransport(host="syslog.test", socket_factory=mock_socket_factory)
        await t.send(["CEF:0|test1", "CEF:0|test2"])
        assert writer.write.call_count == 2

    def test_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_SYSLOG_HOST", "qradar.bank.internal")
        monkeypatch.setenv("IRONCORE_SYSLOG_PORT", "6514")
        monkeypatch.setenv("IRONCORE_SYSLOG_TLS", "true")
        t = SyslogTCPTransport.from_env()
        assert t._host == "qradar.bank.internal"
        assert t._port == 6514
        assert t._use_tls is True


# ══════════════════════════════════════════════════════════════════════════════
#  TestDatadogTransport
# ══════════════════════════════════════════════════════════════════════════════

class TestDatadogTransport:
    @pytest.mark.asyncio
    async def test_send_stub_no_error(self) -> None:
        t = DatadogTransport(api_key="key123")
        await t.send(["CEF:0|test"])

    @pytest.mark.asyncio
    async def test_health_check_stub_returns_true(self) -> None:
        t = DatadogTransport(api_key="key")
        assert await t.health_check() is True

    @pytest.mark.asyncio
    async def test_send_with_http_client(self) -> None:
        resp = MagicMock()
        resp.status_code = 202
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=resp)

        t = DatadogTransport(api_key="key", http_client=mock_http)
        await t.send(["CEF:0|test"])
        mock_http.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_http_error_raises(self) -> None:
        resp = MagicMock()
        resp.status_code = 403
        mock_http = MagicMock()
        mock_http.post = AsyncMock(return_value=resp)

        t = DatadogTransport(api_key="bad-key", http_client=mock_http)
        with pytest.raises(RuntimeError, match="HTTP 403"):
            await t.send(["CEF:0|test"])

    @pytest.mark.asyncio
    async def test_health_check_valid(self) -> None:
        resp = MagicMock()
        resp.json = lambda: {"valid": True}
        mock_http = MagicMock()
        mock_http.get = AsyncMock(return_value=resp)

        t = DatadogTransport(api_key="key", http_client=mock_http)
        assert await t.health_check() is True

    def test_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_DATADOG_API_KEY", "dd-api-123")
        monkeypatch.setenv("IRONCORE_DATADOG_SITE", "datadoghq.eu")
        t = DatadogTransport.from_env()
        assert t._api_key == "dd-api-123"
        assert t._site == "datadoghq.eu"
        assert "datadoghq.eu" in t._endpoint

    def test_build_payload_structure(self) -> None:
        t = DatadogTransport(api_key="k")
        payload = t._build_payload(["CEF:0|line1", "CEF:0|line2"])
        import json
        data = json.loads(payload)
        assert len(data) == 2
        assert data[0]["ddsource"] == "ironcore"
        assert "CEF:0|line1" == data[0]["message"]


# ══════════════════════════════════════════════════════════════════════════════
#  TestSIEMStreamer
# ══════════════════════════════════════════════════════════════════════════════

class TestSIEMStreamer:
    def test_edition_guard_community_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_EDITION", "community")
        with pytest.raises(RuntimeError, match="Enterprise"):
            _make_streamer()
        monkeypatch.setenv("IRONCORE_EDITION", "enterprise")

    def test_edition_guard_enterprise_ok(self) -> None:
        s = _make_streamer()
        assert s is not None

    @pytest.mark.asyncio
    async def test_emit_adds_to_buffer(self) -> None:
        s = _make_streamer()
        await s.emit(_entry())
        assert s.buffer_len == 1

    @pytest.mark.asyncio
    async def test_emit_multiple(self) -> None:
        s = _make_streamer()
        for i in range(5):
            await s.emit(_entry(seq=i + 1))
        assert s.buffer_len == 5

    @pytest.mark.asyncio
    async def test_buffer_overflow_evicts_oldest(self) -> None:
        s = _make_streamer()
        s._buffer_size = 3
        from collections import deque
        s._buffer = deque(maxlen=3)
        for i in range(5):
            await s.emit(_entry(seq=i + 1))
        # deque(maxlen=3) keeps last 3
        assert s.buffer_len == 3

    @pytest.mark.asyncio
    async def test_flush_once_clears_buffer(self) -> None:
        s = _make_streamer()
        await s.emit(_entry(seq=1))
        await s.emit(_entry(seq=2))
        await s._flush_once()
        assert s.buffer_len == 0

    @pytest.mark.asyncio
    async def test_flush_once_calls_transport_send(self) -> None:
        mock_transport = MagicMock(spec=BaseSIEMTransport)
        mock_transport.send = AsyncMock()
        s = _make_streamer(transports=[mock_transport])
        await s.emit(_entry())
        await s._flush_once()
        mock_transport.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_flush_once_empty_no_transport_call(self) -> None:
        mock_transport = MagicMock(spec=BaseSIEMTransport)
        mock_transport.send = AsyncMock()
        s = _make_streamer(transports=[mock_transport])
        await s._flush_once()  # empty buffer
        mock_transport.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fan_out_to_multiple_transports(self) -> None:
        t1 = MagicMock(spec=BaseSIEMTransport)
        t1.send = AsyncMock()
        t2 = MagicMock(spec=BaseSIEMTransport)
        t2.send = AsyncMock()

        s = _make_streamer(transports=[t1, t2])
        await s.emit(_entry(seq=1))
        await s._flush_once()

        t1.send.assert_awaited_once()
        t2.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retry_on_transport_failure(self) -> None:
        failing = MagicMock(spec=BaseSIEMTransport)
        failing.send = AsyncMock(side_effect=ConnectionError("down"))

        s = _make_streamer(transports=[failing])
        # _send_with_retry should retry 3 times then raise
        with pytest.raises(ConnectionError):
            await s._send_with_retry(failing, ["CEF:0|test"])
        assert failing.send.await_count == 3

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self) -> None:
        call_count = {"n": 0}

        async def flaky_send(events):
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise ConnectionError("temporary")

        transport = MagicMock(spec=BaseSIEMTransport)
        transport.send = flaky_send
        s = _make_streamer(transports=[transport])
        # Should resolve after 2 attempts (but we skip real sleep)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await s._send_with_retry(transport, ["CEF:0|test"])
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_failsafe_written_when_all_transports_fail(self, tmp_path) -> None:
        failing = MagicMock(spec=BaseSIEMTransport)
        failing.send = AsyncMock(side_effect=ConnectionError("down"))
        failsafe = str(tmp_path / "failsafe.log")

        s = _make_streamer(transports=[failing], failsafe_path=failsafe)
        await s.emit(_entry(seq=1))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await s._flush_once()

        assert Path(failsafe).exists()
        content = Path(failsafe).read_text()
        assert len(content) > 0

    @pytest.mark.asyncio
    async def test_sent_count_increments(self) -> None:
        mock_transport = MagicMock(spec=BaseSIEMTransport)
        mock_transport.send = AsyncMock()
        s = _make_streamer(transports=[mock_transport])
        for i in range(3):
            await s.emit(_entry(seq=i + 1))
        await s._flush_once()
        assert s.sent_count == 3

    @pytest.mark.asyncio
    async def test_failed_count_increments_on_permanent_failure(self) -> None:
        failing = MagicMock(spec=BaseSIEMTransport)
        failing.send = AsyncMock(side_effect=ConnectionError("down"))
        s = _make_streamer(transports=[failing])
        await s.emit(_entry(seq=1))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await s._flush_once()
        assert s.failed_count >= 1

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self) -> None:
        mock_transport = MagicMock(spec=BaseSIEMTransport)
        mock_transport.send = AsyncMock()
        s = _make_streamer(transports=[mock_transport], flush_interval=100.0)
        await s.start()
        assert s._running is True
        assert s._flush_task is not None
        await s.stop()
        assert s._running is False

    @pytest.mark.asyncio
    async def test_start_idempotent(self) -> None:
        s = _make_streamer(flush_interval=100.0)
        await s.start()
        task1 = s._flush_task
        await s.start()  # second start, should be no-op
        task2 = s._flush_task
        assert task1 is task2
        await s.stop()

    @pytest.mark.asyncio
    async def test_dlp_masking_applied(self) -> None:
        """When dlp_engine is provided, CEF lines should be masked before delivery."""
        mock_dlp = MagicMock()
        mock_dlp.mask = MagicMock(side_effect=lambda line: line.replace("4111111111111111", "****************"))

        mock_transport = MagicMock(spec=BaseSIEMTransport)
        captured = []

        async def capture_send(events):
            captured.extend(events)

        mock_transport.send = capture_send

        s = _make_streamer(transports=[mock_transport], dlp_engine=mock_dlp)
        entry = _entry(payload={"card": "4111111111111111"})
        await s.emit(entry)
        await s._flush_once()

        # DLP mask should have been called for each CEF line
        assert mock_dlp.mask.called

    @pytest.mark.asyncio
    async def test_flush_converts_entries_to_cef(self) -> None:
        """Flush should call format_batch on the formatter."""
        mock_transport = MagicMock(spec=BaseSIEMTransport)
        mock_transport.send = AsyncMock()
        formatter = CEFFormatter()

        received_entries = []
        original_format = formatter.format_batch

        def spy_format(entries):
            received_entries.extend(entries)
            return original_format(entries)

        formatter.format_batch = spy_format
        s = SIEMStreamer(
            transports=[mock_transport],
            formatter=formatter,
            buffer_size=100,
            flush_interval=100.0,
            failsafe_path="/tmp/failsafe-test-spy.log",
        )
        await s.emit(_entry(seq=10))
        await s._flush_once()
        assert any(e.seq == 10 for e in received_entries)


# ══════════════════════════════════════════════════════════════════════════════
#  TestSIEMStreamerFromEnv
# ══════════════════════════════════════════════════════════════════════════════

class TestSIEMStreamerFromEnv:
    def test_from_env_splunk(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_SIEM_TRANSPORTS", "splunk")
        monkeypatch.setenv("IRONCORE_SPLUNK_HEC_URL", "https://splunk.test:8088")
        monkeypatch.setenv("IRONCORE_SPLUNK_HEC_TOKEN", "hec-tok")
        monkeypatch.setenv("IRONCORE_SIEM_BUFFER_SIZE", "5000")
        monkeypatch.setenv("IRONCORE_SIEM_FLUSH_INTERVAL", "1.5")

        s = SIEMStreamer.from_env()
        assert s._buffer_size == 5000
        assert s._flush_interval == 1.5
        assert len(s._transports) == 1
        assert isinstance(s._transports[0], SplunkHECTransport)

    def test_from_env_multiple_transports(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_SIEM_TRANSPORTS", "splunk,datadog")
        monkeypatch.setenv("IRONCORE_SPLUNK_HEC_URL", "https://splunk.test:8088")
        monkeypatch.setenv("IRONCORE_SPLUNK_HEC_TOKEN", "tok")
        monkeypatch.setenv("IRONCORE_DATADOG_API_KEY", "dd-key")
        s = SIEMStreamer.from_env()
        assert len(s._transports) == 2

    def test_from_env_unknown_transport_skipped(self, monkeypatch) -> None:
        monkeypatch.setenv("IRONCORE_SIEM_TRANSPORTS", "splunk,nonexistent")
        monkeypatch.setenv("IRONCORE_SPLUNK_HEC_URL", "https://splunk.test:8088")
        monkeypatch.setenv("IRONCORE_SPLUNK_HEC_TOKEN", "tok")
        s = SIEMStreamer.from_env()
        # Only splunk should be registered
        assert len(s._transports) == 1


# ══════════════════════════════════════════════════════════════════════════════
#  TestIntegration — End-to-end stub flow
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_pipeline_cef_to_splunk(self) -> None:
        """Emit several events → flush → verify CEF delivered to Splunk HEC."""
        received = []

        async def mock_send(events):
            received.extend(events)

        transport = MagicMock(spec=BaseSIEMTransport)
        transport.send = mock_send

        s = _make_streamer(transports=[transport])

        event_types = [
            "action_executed", "dlp_pii_detected", "approval_requested",
            "auth_failure", "airgap_violation",
        ]
        for i, et in enumerate(event_types, start=1):
            await s.emit(_entry(event_type=et, seq=i))

        await s._flush_once()

        assert len(received) == 5
        assert all(line.startswith("CEF:0|") for line in received)
        assert any("500" in line for line in received)   # dlp_pii_detected
        assert any("700" in line for line in received)   # airgap_violation

    @pytest.mark.asyncio
    async def test_overflow_does_not_raise(self) -> None:
        """Emitting more events than buffer_size should not raise."""
        s = SIEMStreamer(
            transports=[SplunkHECTransport(url="https://x", hec_token="t")],
            formatter=CEFFormatter(),
            buffer_size=10,
            flush_interval=100.0,
            failsafe_path="/tmp/overflow-test.log",
        )
        for i in range(50):  # emit 5× buffer capacity
            await s.emit(_entry(seq=i + 1))
        # Should not raise, buffer is capped at 10
        assert s.buffer_len <= 10
