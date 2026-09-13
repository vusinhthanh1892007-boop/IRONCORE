"""Air-Gapped Deployment configuration for IronCore Enterprise.

All settings are validated at instantiation time so bad configs
fail fast at startup rather than at request time.
"""

from __future__ import annotations

import os
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from ironcore.edition import check_enterprise


class AirGapConfig(BaseModel):
    """Centralised config for an air-gapped (offline-only) deployment.

    Validates that no external endpoint is reachable when the environment
    is set to ``production``.

    Typical construction::

        os.environ["IRONCORE_EDITION"] = "enterprise"
        cfg = AirGapConfig.from_env()
    """

    # ── Internal LLM endpoints ────────────────────────────────────────────────
    vllm_base_url: str = "http://gpu-server-01:8080/v1"
    vllm_api_key: str = "internal-key"
    vllm_models: List[str] = Field(
        default_factory=lambda: ["llama3-70b-instruct", "qwen2-72b"]
    )
    ollama_base_url: str = "http://ollama-internal:11434"

    # ── Network policy ────────────────────────────────────────────────────────
    allow_external_network: bool = False
    allowed_internal_cidrs: List[str] = Field(
        default_factory=lambda: ["10.0.0.0/8", "192.168.0.0/16", "172.16.0.0/12"]
    )

    # ── TLS / Certificates ────────────────────────────────────────────────────
    internal_ca_cert_path: Optional[str] = None
    verify_ssl: bool = True

    # ── Docker / registry ─────────────────────────────────────────────────────
    docker_registry: str = ""

    # ── Startup probe timeouts ────────────────────────────────────────────────
    startup_check_timeout: float = 3.0   # seconds per external probe

    # ── Validators ───────────────────────────────────────────────────────────

    @field_validator("allow_external_network")
    @classmethod
    def must_be_false_in_production(cls, v: bool) -> bool:
        env = os.getenv("IRONCORE_ENV", "development").strip().lower()
        if env == "production" and v:
            raise ValueError(
                "allow_external_network MUST be False in production. "
                "This is a hard security requirement for air-gapped deployment."
            )
        return v

    @field_validator("vllm_base_url")
    @classmethod
    def reject_external_llm_urls(cls, v: str) -> str:
        external_hosts = (
            "api.openai.com",
            "api.anthropic.com",
            "generativelanguage.googleapis.com",
            "api.together.xyz",
        )
        for host in external_hosts:
            if host in v:
                raise ValueError(
                    f"vllm_base_url must point to an internal endpoint, "
                    f"not external host '{host}'."
                )
        return v

    # ── Constructors ──────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "AirGapConfig":
        """Build config from environment variables (Enterprise only)."""
        check_enterprise("airgap_deployment")

        models_raw = os.getenv("IRONCORE_VLLM_MODELS", "llama3-70b-instruct,qwen2-72b")
        cidrs_raw = os.getenv(
            "IRONCORE_AIRGAP_ALLOWED_CIDRS",
            "10.0.0.0/8,192.168.0.0/16,172.16.0.0/12",
        )
        return cls(
            vllm_base_url=os.getenv("IRONCORE_VLLM_BASE_URL", "http://gpu-server-01:8080/v1"),
            vllm_api_key=os.getenv("IRONCORE_VLLM_API_KEY", "internal-key"),
            vllm_models=[m.strip() for m in models_raw.split(",") if m.strip()],
            ollama_base_url=os.getenv("IRONCORE_OLLAMA_BASE_URL", "http://ollama-internal:11434"),
            allow_external_network=os.getenv("IRONCORE_AIRGAP_ALLOW_EXTERNAL", "false").lower() == "true",
            allowed_internal_cidrs=[c.strip() for c in cidrs_raw.split(",") if c.strip()],
            internal_ca_cert_path=os.getenv("IRONCORE_INTERNAL_CA_CERT") or None,
            docker_registry=os.getenv("DOCKER_REGISTRY", ""),
        )
