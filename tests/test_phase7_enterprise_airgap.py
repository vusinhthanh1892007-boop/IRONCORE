"""Phase 7 — Enterprise Air-Gapped Deployment — Test Suite.

All tests are self-contained: no real network calls, no real Redis,
no real vLLM.  The network guard tests use monkeypatching of
socket.gethostbyname so DNS resolution never actually happens.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import sys
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Force enterprise edition for all tests ────────────────────────────────────
os.environ["IRONCORE_EDITION"] = "enterprise"

from ironcore.enterprise.airgap.config import AirGapConfig
from ironcore.enterprise.airgap.llm_config import (
    get_airgap_litellm_config,
    get_airgap_model_names,
)
from ironcore.enterprise.airgap.network_guard import (
    AirGapNetworkGuard,
    NetworkViolationError,
)
from ironcore.enterprise.airgap.startup_check import _EXTERNAL_PROBES, airgap_startup_check


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _default_config(**overrides: Any) -> AirGapConfig:
    """Return a valid AirGapConfig with safe defaults."""
    base = dict(
        vllm_base_url="http://gpu-server.internal:8080/v1",
        vllm_api_key="test-key",
        vllm_models=["llama3-70b", "qwen-72b"],
        ollama_base_url="http://ollama.internal:11434",
        allow_external_network=False,
        allowed_internal_cidrs=["10.0.0.0/8", "192.168.0.0/16"],
        docker_registry="registry.internal:5000",
    )
    base.update(overrides)
    return AirGapConfig(**base)


# ══════════════════════════════════════════════════════════════════════════════
#  TestAirGapConfig
# ══════════════════════════════════════════════════════════════════════════════

class TestAirGapConfig:
    def test_default_allow_external_is_false(self) -> None:
        cfg = _default_config()
        assert cfg.allow_external_network is False

    def test_allowed_models_stored(self) -> None:
        cfg = _default_config()
        assert "llama3-70b" in cfg.vllm_models
        assert "qwen-72b" in cfg.vllm_models

    def test_internal_vllm_url_accepted(self) -> None:
        cfg = _default_config(vllm_base_url="http://10.0.1.50:8080/v1")
        assert "10.0.1.50" in cfg.vllm_base_url

    def test_external_openai_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="external"):
            AirGapConfig(
                vllm_base_url="https://api.openai.com/v1",
                allow_external_network=False,
            )

    def test_external_anthropic_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="external"):
            AirGapConfig(vllm_base_url="https://api.anthropic.com/v1")

    def test_allow_external_true_in_production_raises(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("IRONCORE_ENV", "production")
        with pytest.raises(ValueError, match="MUST be False"):
            AirGapConfig(
                vllm_base_url="http://gpu.internal:8080/v1",
                allow_external_network=True,
            )

    def test_allow_external_true_in_dev_accepted(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("IRONCORE_ENV", "development")
        cfg = AirGapConfig(
            vllm_base_url="http://gpu.internal:8080/v1",
            allow_external_network=True,
        )
        assert cfg.allow_external_network is True

    def test_cidr_list_stored(self) -> None:
        cfg = _default_config(allowed_internal_cidrs=["10.0.0.0/8", "172.16.0.0/12"])
        assert "10.0.0.0/8" in cfg.allowed_internal_cidrs

    def test_ca_cert_path_optional(self) -> None:
        cfg = _default_config(internal_ca_cert_path="/certs/ca.crt")
        assert cfg.internal_ca_cert_path == "/certs/ca.crt"

    def test_from_env_reads_env_vars(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("IRONCORE_VLLM_BASE_URL", "http://internal-llm:8080/v1")
        monkeypatch.setenv("IRONCORE_VLLM_MODELS", "llama3,mistral")
        monkeypatch.setenv("IRONCORE_AIRGAP_ALLOWED_CIDRS", "10.0.0.0/8")
        cfg = AirGapConfig.from_env()
        assert "internal-llm" in cfg.vllm_base_url
        assert "llama3" in cfg.vllm_models
        assert "mistral" in cfg.vllm_models

    def test_from_env_requires_enterprise_edition(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("IRONCORE_EDITION", "community")
        with pytest.raises(RuntimeError, match="Enterprise"):
            AirGapConfig.from_env()
        monkeypatch.setenv("IRONCORE_EDITION", "enterprise")  # restore


# ══════════════════════════════════════════════════════════════════════════════
#  TestAirGapNetworkGuard
# ══════════════════════════════════════════════════════════════════════════════

class TestAirGapNetworkGuard:
    def _guard(self, **kw: Any) -> AirGapNetworkGuard:
        return AirGapNetworkGuard(_default_config(**kw))

    def test_internal_ip_10_allowed(self) -> None:
        guard = self._guard()
        ip = ipaddress.IPv4Address("10.1.2.3")
        assert guard._is_internal_ip(ip) is True

    def test_internal_ip_192_168_allowed(self) -> None:
        guard = self._guard()
        ip = ipaddress.IPv4Address("192.168.1.100")
        assert guard._is_internal_ip(ip) is True

    def test_external_ip_blocked(self) -> None:
        guard = self._guard()
        ip = ipaddress.IPv4Address("1.2.3.4")
        assert guard._is_internal_ip(ip) is False

    def test_cloudflare_ip_blocked(self) -> None:
        guard = self._guard()
        ip = ipaddress.IPv4Address("104.16.133.229")  # Cloudflare
        assert guard._is_internal_ip(ip) is False

    def test_is_allowed_host_internal_resolves(self) -> None:
        guard = self._guard()
        with patch("socket.gethostbyname", return_value="10.0.1.50"):
            assert guard.is_allowed_host("gpu-server.internal") is True

    def test_is_allowed_host_external_denied(self) -> None:
        guard = self._guard()
        with patch("socket.gethostbyname", return_value="1.2.3.4"):
            assert guard.is_allowed_host("api.openai.com") is False

    def test_is_allowed_host_dns_fail_denied(self) -> None:
        guard = self._guard()
        with patch("socket.gethostbyname", side_effect=socket.gaierror):
            assert guard.is_allowed_host("nonexistent.external.com") is False

    def test_check_host_internal_passes(self) -> None:
        guard = self._guard()
        with patch("socket.gethostbyname", return_value="192.168.1.10"):
            guard._check_host("safe-internal.host")  # should not raise

    def test_check_host_external_raises(self) -> None:
        guard = self._guard()
        with patch("socket.gethostbyname", return_value="203.0.113.5"):
            with pytest.raises(NetworkViolationError):
                guard._check_host("api.openai.com")

    def test_allow_external_network_bypasses_check(self) -> None:
        guard = self._guard(allow_external_network=True)
        # Even with "external" IP resolution, should pass when flag=True
        with patch("socket.gethostbyname", return_value="8.8.8.8"):
            assert guard.is_allowed_host("google.com") is True

    def test_172_16_not_in_default_guard_unless_cidr_added(self) -> None:
        guard = AirGapNetworkGuard(
            _default_config(allowed_internal_cidrs=["10.0.0.0/8"])
        )
        ip = ipaddress.IPv4Address("172.16.0.1")
        assert guard._is_internal_ip(ip) is False

    def test_172_16_allowed_when_cidr_added(self) -> None:
        guard = AirGapNetworkGuard(
            _default_config(allowed_internal_cidrs=["172.16.0.0/12"])
        )
        ip = ipaddress.IPv4Address("172.16.0.1")
        assert guard._is_internal_ip(ip) is True

    def test_invalid_cidr_skipped_gracefully(self) -> None:
        # Should not raise — invalid CIDRs are logged and skipped
        guard = AirGapNetworkGuard(
            _default_config(allowed_internal_cidrs=["not-a-cidr", "10.0.0.0/8"])
        )
        ip = ipaddress.IPv4Address("10.5.5.5")
        assert guard._is_internal_ip(ip) is True


# ══════════════════════════════════════════════════════════════════════════════
#  TestAirGapLLMConfig
# ══════════════════════════════════════════════════════════════════════════════

class TestAirGapLLMConfig:
    def test_telemetry_disabled(self) -> None:
        cfg = get_airgap_litellm_config(_default_config())
        assert cfg["telemetry"] is False

    def test_model_list_contains_all_models(self) -> None:
        airgap = _default_config(vllm_models=["llama3", "qwen-72b"])
        cfg = get_airgap_litellm_config(airgap)
        model_names = [m["model_name"] for m in cfg["model_list"]]
        assert "llama3" in model_names
        assert "qwen-72b" in model_names

    def test_model_litellm_params_use_internal_base_url(self) -> None:
        airgap = _default_config(
            vllm_base_url="http://internal-gpu:9000/v1",
            vllm_models=["llama3"],
        )
        cfg = get_airgap_litellm_config(airgap)
        vllm_models = [
            m for m in cfg["model_list"]
            if "openai/" in m["litellm_params"]["model"]
        ]
        assert len(vllm_models) >= 1
        assert vllm_models[0]["litellm_params"]["api_base"] == "http://internal-gpu:9000/v1"

    def test_no_external_openai_in_model_list(self) -> None:
        cfg = get_airgap_litellm_config(_default_config())
        for m in cfg["model_list"]:
            params = m["litellm_params"]
            base = params.get("api_base", "")
            assert "openai.com" not in base
            assert "anthropic.com" not in base

    def test_success_and_failure_callbacks_empty(self) -> None:
        cfg = get_airgap_litellm_config(_default_config())
        assert cfg["success_callback"] == []
        assert cfg["failure_callback"] == []

    def test_litellm_telemetry_env_var_set(self) -> None:
        import importlib

        import ironcore.enterprise.airgap.llm_config as lm_mod

        importlib.reload(lm_mod)
        assert os.environ.get("LITELLM_TELEMETRY") == "false"

    def test_get_model_names_returns_list(self) -> None:
        airgap = _default_config(vllm_models=["alpha", "beta"])
        names = get_airgap_model_names(airgap)
        assert names == ["alpha", "beta"]

    def test_ca_cert_used_as_ssl_verify(self) -> None:
        airgap = _default_config(
            internal_ca_cert_path="/certs/bank.crt",
            vllm_models=["llama3"],
        )
        cfg = get_airgap_litellm_config(airgap)
        vllm_entry = next(
            m for m in cfg["model_list"]
            if m["litellm_params"].get("api_base")
        )
        assert vllm_entry["litellm_params"]["ssl_verify"] == "/certs/bank.crt"

    def test_no_ca_cert_uses_verify_ssl_flag(self) -> None:
        airgap = _default_config(
            internal_ca_cert_path=None,
            verify_ssl=True,
            vllm_models=["llama3"],
        )
        cfg = get_airgap_litellm_config(airgap)
        vllm_entry = next(
            m for m in cfg["model_list"]
            if "openai/" in m["litellm_params"]["model"]
        )
        assert vllm_entry["litellm_params"]["ssl_verify"] is True


# ══════════════════════════════════════════════════════════════════════════════
#  TestAirGapStartupCheck
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestAirGapStartupCheck:
    async def test_all_external_blocked_passes(self) -> None:
        """When all external probes timeout, check should pass without raising."""
        async def _probe_always_blocked(host: str, port: int, timeout: float) -> bool:
            return False

        with patch(
            "ironcore.enterprise.airgap.startup_check._tcp_probe",
            side_effect=_probe_always_blocked,
        ):
            await airgap_startup_check(_default_config(), fail_on_external=False)
            # No exception = pass

    async def test_external_reachable_raises_system_exit(self) -> None:
        """When an external host is reachable, fail_on_external should SystemExit."""
        call_count = 0

        async def _probe_first_open(host: str, port: int, timeout: float) -> bool:
            nonlocal call_count
            call_count += 1
            return call_count == 1  # First probe "reachable"

        with patch(
            "ironcore.enterprise.airgap.startup_check._tcp_probe",
            side_effect=_probe_first_open,
        ):
            with pytest.raises(SystemExit):
                await airgap_startup_check(_default_config(), fail_on_external=True)

    async def test_external_reachable_no_fail_returns(self) -> None:
        """With fail_on_external=False, violations are logged but no exception."""
        async def _all_open(host: str, port: int, timeout: float) -> bool:
            return True

        with patch(
            "ironcore.enterprise.airgap.startup_check._tcp_probe",
            side_effect=_all_open,
        ):
            # Should not raise even though all external hosts are "reachable"
            await airgap_startup_check(_default_config(), fail_on_external=False)

    async def test_tcp_probe_timeout_returns_false(self) -> None:
        """_tcp_probe returns False when connection times out."""
        from ironcore.enterprise.airgap.startup_check import _tcp_probe

        with patch(
            "asyncio.open_connection",
            side_effect=asyncio.TimeoutError,
        ):
            result = await _tcp_probe("api.openai.com", 443, 0.1)
            assert result is False

    async def test_tcp_probe_oserror_returns_false(self) -> None:
        from ironcore.enterprise.airgap.startup_check import _tcp_probe

        with patch(
            "asyncio.open_connection",
            side_effect=OSError("unreachable"),
        ):
            result = await _tcp_probe("api.openai.com", 443, 0.1)
            assert result is False

    async def test_tcp_probe_success_returns_true(self) -> None:
        from ironcore.enterprise.airgap.startup_check import _tcp_probe

        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch(
            "asyncio.open_connection",
            new_callable=AsyncMock,
            return_value=(MagicMock(), mock_writer),
        ):
            result = await _tcp_probe("10.0.1.50", 8080, 1.0)
            assert result is True

    async def test_external_probes_list_contains_known_domains(self) -> None:
        # Verify the hardcoded probe list includes critical external domains
        domains = [host for host, _ in _EXTERNAL_PROBES]
        assert "api.openai.com" in domains
        assert "api.anthropic.com" in domains
        assert "pypi.org" in domains

    async def test_startup_check_uses_config_timeout(self) -> None:
        """Startup check passes config timeout to _tcp_probe."""
        timeouts_seen: List[float] = []

        async def _capture_timeout(host: str, port: int, timeout: float) -> bool:
            timeouts_seen.append(timeout)
            return False

        cfg = _default_config(startup_check_timeout=1.5)
        with patch(
            "ironcore.enterprise.airgap.startup_check._tcp_probe",
            side_effect=_capture_timeout,
        ):
            await airgap_startup_check(cfg, fail_on_external=False)

        assert all(t == 1.5 for t in timeouts_seen)
