"""
IronCore Model Registry – real-time model catalog fetcher.

Fetches the latest AI models from OpenRouter API and provides
a unified registry for TUI, Web, and Docker components.
"""

import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

OPENROUTER_API = "https://openrouter.ai/api/v1/models"
CACHE_DIR = Path.home() / ".ironcore" / "cache"
CACHE_FILE = CACHE_DIR / "model_registry.json"
CACHE_TTL = 3600  # 1 hour

PROVIDER_MAP = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "meta-llama": "Meta",
    "meta": "Meta",
    "mistralai": "Mistral",
    "deepseek": "DeepSeek",
    "cohere": "Cohere",
    "qwen": "Qwen (Alibaba)",
    "alibaba": "Alibaba",
    "x-ai": "xAI",
    "nvidia": "NVIDIA",
    "minimax": "MiniMax",
    "moonshotai": "Moonshot",
    "z-ai": "Z.ai (GLM)",
    "tencent": "Tencent",
    "bytedance-seed": "ByteDance",
    "bytedance": "ByteDance",
    "baidu": "Baidu",
    "arcee-ai": "Arcee AI",
    "perplexity": "Perplexity",
    "liquid": "Liquid AI",
    "ibm-granite": "IBM",
    "nousresearch": "Nous Research",
    "stepfun": "StepFun",
    "upstage": "Upstage",
    "writer": "Writer",
    "amazon": "Amazon",
    "inflection": "Inflection",
    "kwaipilot": "KwaiKAT",
    "xiaomi": "Xiaomi",
    "allenai": "Allen AI",
    "essentialai": "Essential AI",
    "nex-agi": "Nex AGI",
}


@dataclass
class ModelInfo:
    id: str
    name: str
    provider: str
    provider_name: str
    context_length: int
    modality: str
    pricing_prompt: float
    pricing_completion: float
    is_free: bool
    tags: list[str] = field(default_factory=list)


@dataclass
class ProviderSummary:
    id: str
    name: str
    model_count: int
    top_models: list[str]


def _extract_provider(model_id: str) -> str:
    return model_id.split("/")[0] if "/" in model_id else "unknown"


def _resolve_provider_name(provider_slug: str) -> str:
    return PROVIDER_MAP.get(provider_slug, provider_slug.replace("-", " ").title())


def _parse_model(raw: dict) -> ModelInfo:
    model_id = raw.get("id", "")
    provider_slug = _extract_provider(model_id)
    pricing = raw.get("pricing", {})
    prompt_price = float(pricing.get("prompt", 0) or 0)
    completion_price = float(pricing.get("completion", 0) or 0)
    arch = raw.get("architecture", {})
    modality = arch.get("modality", "text->text")
    ctx = raw.get("context_length", 0) or 0

    tags = []
    input_mods = arch.get("input_modalities", [])
    output_mods = arch.get("output_modalities", [])
    if "image" in input_mods:
        tags.append("vision")
    if "audio" in input_mods:
        tags.append("audio")
    if "video" in input_mods:
        tags.append("video")
    if "image" in output_mods:
        tags.append("image-gen")
    if prompt_price == 0 and completion_price == 0:
        tags.append("free")
    if ctx >= 500000:
        tags.append("long-context")
    if "code" in model_id.lower() or "codex" in model_id.lower() or "coder" in model_id.lower():
        tags.append("coding")
    if "thinking" in model_id.lower() or "reasoning" in raw.get("name", "").lower():
        tags.append("reasoning")

    return ModelInfo(
        id=model_id,
        name=raw.get("name", model_id),
        provider=provider_slug,
        provider_name=_resolve_provider_name(provider_slug),
        context_length=ctx,
        modality=modality,
        pricing_prompt=prompt_price,
        pricing_completion=completion_price,
        is_free=(prompt_price == 0 and completion_price == 0),
        tags=tags,
    )


def fetch_models(force_refresh: bool = False) -> list[ModelInfo]:
    """Fetch models from OpenRouter API with local caching."""
    if not force_refresh and CACHE_FILE.exists():
        try:
            cache_data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() - cache_data.get("timestamp", 0) < CACHE_TTL:
                return [ModelInfo(**m) for m in cache_data["models"]]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    try:
        req = urllib.request.Request(
            OPENROUTER_API,
            headers={"User-Agent": "IronCore/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_data = json.loads(resp.read().decode())
    except Exception:
        # Fallback to cache if available
        if CACHE_FILE.exists():
            try:
                cache_data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                return [ModelInfo(**m) for m in cache_data["models"]]
            except Exception:
                pass
        return []

    models = []
    for raw_model in raw_data.get("data", []):
        try:
            models.append(_parse_model(raw_model))
        except Exception:
            continue

    # Save cache
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_payload = {
        "timestamp": time.time(),
        "model_count": len(models),
        "models": [
            {
                "id": m.id,
                "name": m.name,
                "provider": m.provider,
                "provider_name": m.provider_name,
                "context_length": m.context_length,
                "modality": m.modality,
                "pricing_prompt": m.pricing_prompt,
                "pricing_completion": m.pricing_completion,
                "is_free": m.is_free,
                "tags": m.tags,
            }
            for m in models
        ],
    }
    CACHE_FILE.write_text(json.dumps(cache_payload, ensure_ascii=False), encoding="utf-8")
    return models


def get_providers(models: Optional[list[ModelInfo]] = None) -> list[ProviderSummary]:
    """Group models by provider."""
    if models is None:
        models = fetch_models()

    provider_groups: dict[str, list[ModelInfo]] = {}
    for m in models:
        provider_groups.setdefault(m.provider, []).append(m)

    summaries = []
    for slug, group in sorted(provider_groups.items(), key=lambda x: -len(x[1])):
        top = [m.name for m in sorted(group, key=lambda x: -x.context_length)[:5]]
        summaries.append(ProviderSummary(
            id=slug,
            name=_resolve_provider_name(slug),
            model_count=len(group),
            top_models=top,
        ))
    return summaries


def search_models(
    query: str = "",
    provider: str = "",
    tags: Optional[list[str]] = None,
    free_only: bool = False,
    min_context: int = 0,
    models: Optional[list[ModelInfo]] = None,
) -> list[ModelInfo]:
    """Search/filter models."""
    if models is None:
        models = fetch_models()

    results = models
    if provider:
        p = provider.lower()
        results = [m for m in results if m.provider == p or p in m.provider_name.lower()]
    if query:
        q = query.lower()
        results = [m for m in results if q in m.id.lower() or q in m.name.lower()]
    if tags:
        tag_set = set(t.lower() for t in tags)
        results = [m for m in results if tag_set.intersection(m.tags)]
    if free_only:
        results = [m for m in results if m.is_free]
    if min_context > 0:
        results = [m for m in results if m.context_length >= min_context]

    return results


def export_for_tui(models: Optional[list[ModelInfo]] = None) -> list[dict]:
    """Export model list in format compatible with TUI ModelPickerScreen."""
    if models is None:
        models = fetch_models()
    return [
        {
            "id": m.id,
            "name": f"{m.name} ({m.provider_name})",
            "context_length": m.context_length,
        }
        for m in models
    ]


def export_for_web_catalog(models: Optional[list[ModelInfo]] = None) -> dict:
    """Export in web ai-catalog.ts compatible format."""
    if models is None:
        models = fetch_models()

    providers_map: dict[str, dict] = {}
    for m in models:
        if m.provider not in providers_map:
            providers_map[m.provider] = {
                "id": m.provider,
                "name": m.provider_name,
                "models": [],
            }
        providers_map[m.provider]["models"].append({
            "model_id": m.id,
            "model_name": m.name,
            "short_description": f"{m.modality} | ctx:{m.context_length}",
            "context_window": m.context_length,
            "tags": m.tags,
        })

    return {
        "last_updated": time.strftime("%Y-%m-%d"),
        "total_models": len(models),
        "total_providers": len(providers_map),
        "providers": list(providers_map.values()),
    }


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    print("Fetching latest AI models from OpenRouter...")
    all_models = fetch_models(force_refresh=force)
    print(f"\nTotal models: {len(all_models)}")
    providers = get_providers(all_models)
    print(f"Total providers: {len(providers)}\n")
    for p in providers[:20]:
        print(f"  {p.name}: {p.model_count} models")
        for t in p.top_models[:3]:
            print(f"    - {t}")
    free = [m for m in all_models if m.is_free]
    print(f"\nFree models: {len(free)}")
    coding = search_models(tags=["coding"], models=all_models)
    print(f"Coding models: {len(coding)}")
    vision = search_models(tags=["vision"], models=all_models)
    print(f"Vision models: {len(vision)}")
