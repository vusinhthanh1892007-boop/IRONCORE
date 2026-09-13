"""
IronCore Tool: Image Generation
================================
Generate images from text prompts using AI APIs.
Supports: OpenAI DALL-E, Stability AI, Black Forest Labs FLUX.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

import httpx

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)

_OUTPUT_DIR = os.environ.get("IRONCORE_MEDIA_DIR", "/tmp/ironcore-media")


def _ensure_output_dir() -> Path:
    p = Path(_OUTPUT_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


async def _openai_generate(prompt: str, size: str, api_key: str, output_path: Path) -> dict:
    """Generate image using OpenAI DALL-E 3."""
    url = "https://api.openai.com/v1/images/generations"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "dall-e-3",
        "prompt": prompt,
        "n": 1,
        "size": size,
        "response_format": "url",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        image_url = data["data"][0]["url"]
        revised_prompt = data["data"][0].get("revised_prompt", prompt)

        # Download the image
        img_resp = await client.get(image_url)
        img_resp.raise_for_status()
        output_path.write_bytes(img_resp.content)

    return {"provider": "openai_dalle3", "revised_prompt": revised_prompt}


async def _stability_generate(prompt: str, size: str, api_key: str, output_path: Path) -> dict:
    """Generate image using Stability AI."""
    url = "https://api.stability.ai/v2beta/stable-image/generate/sd3"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "image/*"}

    w, h = (1024, 1024)
    if "x" in size:
        parts = size.split("x")
        w, h = int(parts[0]), int(parts[1])

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            url,
            headers=headers,
            data={"prompt": prompt, "output_format": "png", "aspect_ratio": "1:1"},
        )
        resp.raise_for_status()
        output_path.write_bytes(resp.content)

    return {"provider": "stability_sd3"}


async def _flux_generate(prompt: str, api_key: str, output_path: Path) -> dict:
    """Generate image using Black Forest Labs FLUX."""
    url = "https://api.bfl.ml/v1/flux-pro-1.1"
    headers = {"x-key": api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json={"prompt": prompt, "width": 1024, "height": 1024}, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        # FLUX returns a task ID, poll for result
        task_id = data.get("id")
        if task_id:
            for _ in range(30):
                import asyncio
                await asyncio.sleep(2)
                status_resp = await client.get(
                    f"https://api.bfl.ml/v1/get_result?id={task_id}",
                    headers=headers,
                )
                status = status_resp.json()
                if status.get("status") == "Ready":
                    img_url = status["result"]["sample"]
                    img_resp = await client.get(img_url)
                    img_resp.raise_for_status()
                    output_path.write_bytes(img_resp.content)
                    return {"provider": "flux_pro"}

            return {"provider": "flux_pro", "error": "Generation timed out"}

    return {"provider": "flux_pro", "error": "Unknown response format"}


@skill(
    name="image_generate",
    version="1.0.0",
    description="Generate an image from a text prompt. Returns the local file path.",
    long_description=(
        "Multi-provider image generation. Priority: OpenAI DALL-E 3 (OPENAI_API_KEY) → "
        "Stability AI (STABILITY_API_KEY) → Black Forest Labs FLUX (BFL_API_KEY)."
    ),
    author="brain",
    tags=["image", "generation", "ai", "dalle", "stable-diffusion"],
    risk_level=RiskLevel.LOW,
    requires_network=True,
    estimated_latency_ms=15000.0,
    cost_tier="expensive",
    parameters=[
        SkillParameterSchema(name="prompt", type="string", description="Image generation prompt", required=True),
        SkillParameterSchema(
            name="size",
            type="string",
            description="Image size: '1024x1024', '1792x1024', '1024x1792'",
            required=False,
            default="1024x1024",
        ),
        SkillParameterSchema(
            name="provider",
            type="string",
            description="Provider: 'auto', 'openai', 'stability', 'flux'",
            required=False,
            default="auto",
            enum_values=["auto", "openai", "stability", "flux"],
        ),
    ],
)
async def image_generate(
    prompt: str,
    size: str = "1024x1024",
    provider: str = "auto",
) -> str:
    """Generate an image from a text prompt."""
    if not prompt.strip():
        return json.dumps({"error": "Prompt cannot be empty"})

    output_dir = _ensure_output_dir()
    filename = f"img_{uuid.uuid4().hex[:12]}.png"
    output_path = output_dir / filename

    openai_key = os.environ.get("OPENAI_API_KEY")
    stability_key = os.environ.get("STABILITY_API_KEY")
    bfl_key = os.environ.get("BFL_API_KEY")

    errors = []

    if provider in ("auto", "openai") and openai_key:
        try:
            info = await _openai_generate(prompt, size, openai_key, output_path)
            return json.dumps({
                "status": "generated",
                "filepath": str(output_path),
                "size_bytes": output_path.stat().st_size,
                "prompt": prompt,
                **info,
            }, ensure_ascii=False)
        except Exception as exc:
            errors.append(f"openai: {exc}")

    if provider in ("auto", "stability") and stability_key:
        try:
            info = await _stability_generate(prompt, size, stability_key, output_path)
            return json.dumps({
                "status": "generated",
                "filepath": str(output_path),
                "size_bytes": output_path.stat().st_size,
                "prompt": prompt,
                **info,
            }, ensure_ascii=False)
        except Exception as exc:
            errors.append(f"stability: {exc}")

    if provider in ("auto", "flux") and bfl_key:
        try:
            info = await _flux_generate(prompt, bfl_key, output_path)
            if "error" not in info:
                return json.dumps({
                    "status": "generated",
                    "filepath": str(output_path),
                    "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
                    "prompt": prompt,
                    **info,
                }, ensure_ascii=False)
            errors.append(f"flux: {info['error']}")
        except Exception as exc:
            errors.append(f"flux: {exc}")

    return json.dumps({
        "error": "All image generation providers failed",
        "details": errors,
        "hint": "Set OPENAI_API_KEY, STABILITY_API_KEY, or BFL_API_KEY.",
    })
