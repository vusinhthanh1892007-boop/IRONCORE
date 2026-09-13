from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Literal


LocalProviderId = Literal["ollama", "localai", "vllm", "lmstudio"]


@dataclass
class LocalModelInfo:
    id: str
    name: str
    family: str | None = None


@dataclass
class LocalProviderScanResult:
    id: LocalProviderId
    label: str
    base_url: str
    available: bool
    models: list[LocalModelInfo]
    error: str | None = None


def _trim_slash(value: str) -> str:
    return value[:-1] if value.endswith("/") else value


def _normalize_openai_base(base_url: str) -> str:
    trimmed = _trim_slash(base_url)
    if trimmed.endswith("/v1"):
        return trimmed
    return f"{trimmed}/v1"


def _safe_fetch_json(url: str, timeout: float = 0.8) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "IronCore TUI"}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = response.read().decode("utf-8", errors="replace")
        return json.loads(payload)


def _default_ollama_base_url() -> str:
    return _trim_slash(
        os.environ.get("IRONCORE_OLLAMA_BASE_URL")
        or os.environ.get("NEXT_PUBLIC_OLLAMA_BASE_URL")
        or "http://127.0.0.1:11434"
    )


def _default_localai_base_url() -> str:
    return _trim_slash(
        os.environ.get("IRONCORE_LOCALAI_BASE_URL")
        or os.environ.get("NEXT_PUBLIC_LOCALAI_BASE_URL")
        or "http://127.0.0.1:8080"
    )


def _default_vllm_base_url() -> str:
    return _trim_slash(
        os.environ.get("IRONCORE_VLLM_BASE_URL")
        or os.environ.get("NEXT_PUBLIC_VLLM_BASE_URL")
        or "http://127.0.0.1:8001"
    )


def _default_lmstudio_base_url() -> str:
    return _trim_slash(
        os.environ.get("IRONCORE_LMSTUDIO_BASE_URL")
        or os.environ.get("NEXT_PUBLIC_LMSTUDIO_BASE_URL")
        or "http://127.0.0.1:1234"
    )


def _scan_ollama(base_url: str) -> LocalProviderScanResult:
    endpoint = f"{_trim_slash(base_url)}/api/tags"
    try:
        payload = _safe_fetch_json(endpoint)
        items = payload.get("models", []) if isinstance(payload, dict) else []
        models: list[LocalModelInfo] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("model") or item.get("name") or "").strip()
            if not name:
                continue
            details = item.get("details") if isinstance(item.get("details"), dict) else {}
            family = str(details.get("family") or "").strip() or None
            models.append(LocalModelInfo(id=name, name=name, family=family))

        return LocalProviderScanResult(
            id="ollama",
            label="Ollama",
            base_url=_trim_slash(base_url),
            available=True,
            models=models,
        )
    except Exception as exc:
        return LocalProviderScanResult(
            id="ollama",
            label="Ollama",
            base_url=_trim_slash(base_url),
            available=False,
            models=[],
            error=str(exc),
        )


def _scan_openai_compatible(provider_id: LocalProviderId, label: str, base_url: str) -> LocalProviderScanResult:
    normalized = _normalize_openai_base(base_url)
    endpoint = f"{normalized}/models"
    try:
        payload = _safe_fetch_json(endpoint)
        items = payload.get("data", []) if isinstance(payload, dict) else []
        models: list[LocalModelInfo] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("id") or "").strip()
            if not name:
                continue
            models.append(LocalModelInfo(id=name, name=name))

        return LocalProviderScanResult(
            id=provider_id,
            label=label,
            base_url=normalized,
            available=True,
            models=models,
        )
    except Exception as exc:
        return LocalProviderScanResult(
            id=provider_id,
            label=label,
            base_url=normalized,
            available=False,
            models=[],
            error=str(exc),
        )


def scan_local_providers() -> list[LocalProviderScanResult]:
    return [
        _scan_ollama(_default_ollama_base_url()),
        _scan_openai_compatible("localai", "LocalAI", _default_localai_base_url()),
        _scan_openai_compatible("vllm", "vLLM", _default_vllm_base_url()),
        _scan_openai_compatible("lmstudio", "LM Studio", _default_lmstudio_base_url()),
    ]
