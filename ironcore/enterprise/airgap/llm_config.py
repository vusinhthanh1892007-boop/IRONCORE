"""Build LiteLLM configuration for an air-gapped deployment.

All model calls are routed to an internal vLLM (or Ollama) endpoint.
LiteLLM telemetry is explicitly disabled to prevent any data leaving
the air-gapped environment.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from ironcore.enterprise.airgap.config import AirGapConfig

logger = logging.getLogger(__name__)

# Force LiteLLM to never send telemetry — set before litellm is imported.
os.environ.setdefault("LITELLM_TELEMETRY", "false")


def get_airgap_litellm_config(airgap_config: AirGapConfig) -> Dict[str, Any]:
    """Return a LiteLLM *model_list* config that routes to internal vLLM.

    Usage::

        import litellm
        cfg = get_airgap_litellm_config(my_airgap_config)
        litellm.model_list = cfg["model_list"]
        litellm.telemetry = cfg["telemetry"]

    The returned dict has the shape::

        {
            "model_list": [...],
            "telemetry": False,
            "success_callback": [],
            "failure_callback": [],
        }
    """
    ssl_verify: Any = airgap_config.internal_ca_cert_path or airgap_config.verify_ssl

    model_list: List[Dict[str, Any]] = []
    for model_name in airgap_config.vllm_models:
        model_list.append(
            {
                "model_name": model_name,
                "litellm_params": {
                    "model": f"openai/{model_name}",
                    "api_base": airgap_config.vllm_base_url,
                    "api_key": airgap_config.vllm_api_key,
                    "ssl_verify": ssl_verify,
                },
            }
        )

    # Also expose Ollama models if the URL looks like a real host
    if "localhost" not in airgap_config.ollama_base_url and "127.0.0.1" not in airgap_config.ollama_base_url:
        for model_name in airgap_config.vllm_models:
            model_list.append(
                {
                    "model_name": f"ollama/{model_name}",
                    "litellm_params": {
                        "model": f"ollama/{model_name}",
                        "api_base": airgap_config.ollama_base_url,
                        "ssl_verify": ssl_verify,
                    },
                }
            )

    config: Dict[str, Any] = {
        "model_list": model_list,
        # CRITICAL: disable LiteLLM telemetry — no data must leave air-gap
        "telemetry": False,
        # Disable all cloud callbacks
        "success_callback": [],
        "failure_callback": [],
    }

    logger.info(
        "[AirGapLLM] Config built | models=%s vllm_base=%s telemetry=off",
        [m["model_name"] for m in model_list],
        airgap_config.vllm_base_url,
    )
    return config


def get_airgap_model_names(airgap_config: AirGapConfig) -> List[str]:
    """Convenience: return list of model names available in this air-gap setup."""
    return list(airgap_config.vllm_models)
