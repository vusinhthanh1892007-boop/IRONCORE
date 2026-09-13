"""
IronCore Tool: AI Video Generation
====================================
Generate videos from text prompts using open-source AI models.

Supports multiple providers (fallback chain):
  1. Replicate — CogVideoX-5B, Wan 2.1, Stable Video Diffusion (free trial credits)
  2. Fal.ai — CogVideoX, AnimateDiff, Kling (generous free tier)
  3. Hugging Face Inference API — CogVideoX, Mochi (free tier)
  4. ComfyUI local API — Any model running on local ComfyUI server (free, self-hosted)

All models are open-source / open-weight. No vendor lock-in.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)

_OUTPUT_DIR = os.environ.get("IRONCORE_MEDIA_DIR", "/tmp/ironcore-media")
_REQUEST_TIMEOUT = 300  # 5 min — video gen is slow


def _ensure_output_dir() -> Path:
    p = Path(_OUTPUT_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ──────────────────────────────────────────────────────────────────────────────
# Provider 1: Replicate (open-source models on cloud GPU)
# Models: CogVideoX-5B, Wan-2.1, Stable Video Diffusion
# API key: REPLICATE_API_TOKEN
# ──────────────────────────────────────────────────────────────────────────────

async def _replicate_generate(
    prompt: str,
    duration: int,
    resolution: str,
    model_name: str,
    api_key: str,
    output_path: Path,
) -> dict:
    """Generate video using Replicate API with open-source models."""

    # Model mapping to Replicate model IDs
    model_map = {
        "cogvideox-5b": "tencent/cogvideox-5b:81cfd52e815a4b8698d38ec87a694e11a15df29c7674ca44a88a541e9b681897",
        "wan-2.1": "wan-video/wan-2.1:16d17758e6b07ef19bb6c50eb67d0e1ab4120525a8e72f62c3b94e5c81295cb1",
        "stable-video": "stability-ai/stable-video-diffusion:3f0457e4619daac51203dedb472816fd4af51f3149fa7a9e0b5ffcf1b8172438",
    }

    model_id = model_map.get(model_name, model_map["cogvideox-5b"])
    url = "https://api.replicate.com/v1/predictions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Build input based on model
    if "cogvideo" in model_name:
        model_input = {
            "prompt": prompt,
            "num_inference_steps": 30,
            "guidance_scale": 6,
            "num_frames": min(duration * 8, 49),  # CogVideoX limit
        }
    elif "wan" in model_name:
        model_input = {
            "prompt": prompt,
            "num_frames": min(duration * 16, 81),
            "resolution": resolution,
        }
    else:
        model_input = {
            "prompt": prompt,
        }

    payload = {"version": model_id.split(":")[-1], "input": model_input}

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        # Create prediction
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        prediction = resp.json()
        prediction_url = prediction.get("urls", {}).get("get", "")

        if not prediction_url:
            return {"error": "Replicate did not return prediction URL"}

        # Poll for completion
        for _ in range(120):  # max 10 min
            await asyncio.sleep(5)
            poll = await client.get(prediction_url, headers=headers)
            poll.raise_for_status()
            status_data = poll.json()
            status = status_data.get("status", "")

            if status == "succeeded":
                output = status_data.get("output")
                if isinstance(output, list):
                    video_url = output[0]
                elif isinstance(output, str):
                    video_url = output
                else:
                    return {"error": "Unexpected output format from Replicate"}

                # Download video
                video_resp = await client.get(video_url)
                video_resp.raise_for_status()
                output_path.write_bytes(video_resp.content)
                return {
                    "provider": "replicate",
                    "model": model_name,
                    "status": "success",
                }

            elif status == "failed":
                error_msg = status_data.get("error", "Unknown error")
                return {"error": f"Replicate generation failed: {error_msg}"}

        return {"error": "Replicate generation timed out (10 min)"}


# ──────────────────────────────────────────────────────────────────────────────
# Provider 2: Fal.ai (generous free tier, open models)
# Models: CogVideoX, AnimateDiff, Kling
# API key: FAL_KEY
# ──────────────────────────────────────────────────────────────────────────────

async def _fal_generate(
    prompt: str,
    duration: int,
    resolution: str,
    model_name: str,
    api_key: str,
    output_path: Path,
) -> dict:
    """Generate video using Fal.ai API."""

    model_map = {
        "cogvideox-5b": "fal-ai/cogvideox-5b",
        "animatediff": "fal-ai/animatediff-sparsectrl-lcm",
        "kling": "fal-ai/kling-video/v1.6/pro/text-to-video",
        "hunyuan": "fal-ai/hunyuan-video",
    }

    fal_model = model_map.get(model_name, model_map["cogvideox-5b"])
    url = f"https://queue.fal.run/{fal_model}"
    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "prompt": prompt,
        "num_inference_steps": 30,
    }

    # Add resolution if model supports it
    if "x" in resolution:
        w, h = resolution.split("x")
        payload["width"] = int(w)
        payload["height"] = int(h)

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        # Submit to queue
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        queue_data = resp.json()

        status_url = queue_data.get("status_url") or queue_data.get("request_url", "")
        response_url = queue_data.get("response_url", "")

        # If we got a direct result (sync endpoint)
        if "video" in queue_data:
            video_info = queue_data["video"]
            video_url = video_info.get("url", "")
            if video_url:
                video_resp = await client.get(video_url)
                video_resp.raise_for_status()
                output_path.write_bytes(video_resp.content)
                return {"provider": "fal", "model": fal_model, "status": "success"}

        # Async queue — poll for result
        if not response_url and status_url:
            response_url = status_url.replace("/status", "/result") if "/status" in status_url else status_url

        for _ in range(120):
            await asyncio.sleep(5)
            if status_url:
                poll = await client.get(status_url, headers=headers)
                if poll.status_code == 200:
                    poll_data = poll.json()
                    if poll_data.get("status") == "COMPLETED":
                        break
                    elif poll_data.get("status") in ("FAILED", "CANCELLED"):
                        return {"error": f"Fal generation failed: {poll_data.get('error', 'unknown')}"}

        # Fetch result
        if response_url:
            result = await client.get(response_url, headers=headers)
            result.raise_for_status()
            result_data = result.json()
            video_info = result_data.get("video", {})
            video_url = video_info.get("url", "")
            if video_url:
                video_resp = await client.get(video_url)
                video_resp.raise_for_status()
                output_path.write_bytes(video_resp.content)
                return {"provider": "fal", "model": fal_model, "status": "success"}

        return {"error": "Fal generation: could not retrieve result"}


# ──────────────────────────────────────────────────────────────────────────────
# Provider 3: Hugging Face Inference API (free tier)
# Models: CogVideoX, Mochi
# API key: HF_TOKEN
# ──────────────────────────────────────────────────────────────────────────────

async def _huggingface_generate(
    prompt: str,
    duration: int,
    model_name: str,
    api_key: str,
    output_path: Path,
) -> dict:
    """Generate video using HuggingFace Inference API."""

    model_map = {
        "cogvideox-5b": "THUDM/CogVideoX-5b",
        "mochi": "genmo/mochi-1-preview",
    }

    hf_model = model_map.get(model_name, model_map["cogvideox-5b"])
    url = f"https://api-inference.huggingface.co/models/{hf_model}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "inputs": prompt,
        "parameters": {
            "num_inference_steps": 30,
            "num_frames": min(duration * 8, 49),
        },
    }

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code == 503:
            # Model is loading — wait and retry
            estimated_time = resp.json().get("estimated_time", 60)
            logger.info("[AIVideoGen] HF model loading, waiting %.0fs...", estimated_time)
            await asyncio.sleep(min(estimated_time, 120))
            resp = await client.post(url, json=payload, headers=headers)

        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "video" in content_type or "octet-stream" in content_type:
            output_path.write_bytes(resp.content)
            return {"provider": "huggingface", "model": hf_model, "status": "success"}

        # Some endpoints return JSON with a URL
        try:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                video_url = data[0].get("generated_video", "") or data[0].get("url", "")
                if video_url:
                    video_resp = await client.get(video_url)
                    video_resp.raise_for_status()
                    output_path.write_bytes(video_resp.content)
                    return {"provider": "huggingface", "model": hf_model, "status": "success"}
        except Exception:
            pass

        return {"error": "HuggingFace: unexpected response format"}


# ──────────────────────────────────────────────────────────────────────────────
# Provider 4: ComfyUI Local API (self-hosted, free)
# Server: COMFYUI_URL (default: http://127.0.0.1:8188)
# ──────────────────────────────────────────────────────────────────────────────

async def _comfyui_generate(
    prompt: str,
    duration: int,
    resolution: str,
    output_path: Path,
) -> dict:
    """Generate video using local ComfyUI server with AnimateDiff/CogVideoX workflow."""

    base_url = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
    client_id = str(uuid.uuid4())

    # Basic AnimateDiff text-to-video workflow
    workflow = {
        "prompt": {
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["4", 0]},
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "animatediff_lightning_4step_comfyui.safetensors"},
            },
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": int(time.time()) % (2**32),
                    "steps": 8,
                    "cfg": 2.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["3", 0],
                    "negative": ["6", 0],
                    "latent_image": ["7", 0],
                },
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "low quality, blurry, distorted", "clip": ["4", 0]},
            },
            "7": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": int(resolution.split("x")[0]) if "x" in resolution else 512,
                    "height": int(resolution.split("x")[1]) if "x" in resolution else 512,
                    "batch_size": min(duration * 8, 16),
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["5", 0], "vae": ["4", 2]},
            },
            "9": {
                "class_type": "VHS_VideoCombine",
                "inputs": {
                    "images": ["8", 0],
                    "frame_rate": 8,
                    "format": "video/h264-mp4",
                    "filename_prefix": "ironcore_gen",
                },
            },
        },
        "client_id": client_id,
    }

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        # Check if ComfyUI is running
        try:
            health = await client.get(f"{base_url}/system_stats", timeout=5)
            if health.status_code != 200:
                return {"error": "ComfyUI server not responding"}
        except Exception:
            return {"error": f"ComfyUI not available at {base_url}"}

        # Queue prompt
        resp = await client.post(f"{base_url}/prompt", json=workflow)
        if resp.status_code != 200:
            return {"error": f"ComfyUI queue failed: {resp.text[:500]}"}

        prompt_data = resp.json()
        prompt_id = prompt_data.get("prompt_id", "")
        if not prompt_id:
            return {"error": "ComfyUI did not return prompt_id"}

        # Poll for completion
        for _ in range(120):
            await asyncio.sleep(3)
            history_resp = await client.get(f"{base_url}/history/{prompt_id}")
            if history_resp.status_code != 200:
                continue
            history = history_resp.json()
            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                for node_id, node_output in outputs.items():
                    gifs = node_output.get("gifs", [])
                    videos = node_output.get("videos", gifs)
                    if videos:
                        video_info = videos[0]
                        filename = video_info.get("filename", "")
                        subfolder = video_info.get("subfolder", "")
                        view_url = f"{base_url}/view?filename={filename}&subfolder={subfolder}&type=output"
                        video_resp = await client.get(view_url)
                        video_resp.raise_for_status()
                        output_path.write_bytes(video_resp.content)
                        return {"provider": "comfyui_local", "model": "animatediff", "status": "success"}

        return {"error": "ComfyUI generation timed out"}


# ──────────────────────────────────────────────────────────────────────────────
# Main Skill Entry Point
# ──────────────────────────────────────────────────────────────────────────────

@skill(
    name="ai_video_generate",
    version="1.0.0",
    description=(
        "Generate AI video from a text prompt. Uses open-source models: "
        "CogVideoX-5B, Wan 2.1, Stable Video Diffusion, AnimateDiff, Mochi. "
        "Supports Replicate, Fal.ai, HuggingFace, and local ComfyUI as providers."
    ),
    long_description=(
        "Multi-provider AI video generation tool with automatic fallback:\n"
        "1) Replicate — CogVideoX-5B, Wan 2.1, Stable Video Diffusion (cloud GPU)\n"
        "2) Fal.ai — CogVideoX, AnimateDiff, HunyuanVideo (generous free tier)\n"
        "3) HuggingFace — CogVideoX, Mochi (free Inference API)\n"
        "4) ComfyUI — Any local model (self-hosted, totally free)\n\n"
        "Set API keys via environment variables:\n"
        "REPLICATE_API_TOKEN, FAL_KEY, HF_TOKEN\n"
        "For ComfyUI: COMFYUI_URL (default: http://127.0.0.1:8188)"
    ),
    author="brain",
    tags=["video", "ai", "generation", "text-to-video", "open-source", "cogvideox", "wan", "animatediff"],
    risk_level=RiskLevel.LOW,
    requires_sandbox=False,
    requires_network=True,
    estimated_latency_ms=120000.0,  # 2 min typical
    cost_tier="free",
    parameters=[
        SkillParameterSchema(
            name="prompt",
            type="string",
            description="Text description of the video to generate",
            required=True,
        ),
        SkillParameterSchema(
            name="duration",
            type="int",
            description="Desired video length in seconds (1-10, actual depends on model)",
            required=False,
            default=4,
        ),
        SkillParameterSchema(
            name="resolution",
            type="string",
            description="Output resolution: '720x480', '1280x720', '512x512'",
            required=False,
            default="720x480",
            enum_values=["512x512", "720x480", "1280x720"],
        ),
        SkillParameterSchema(
            name="model",
            type="string",
            description="Model to use: 'cogvideox-5b', 'wan-2.1', 'stable-video', 'animatediff', 'mochi', 'hunyuan', 'kling'",
            required=False,
            default="cogvideox-5b",
            enum_values=["cogvideox-5b", "wan-2.1", "stable-video", "animatediff", "mochi", "hunyuan", "kling"],
        ),
        SkillParameterSchema(
            name="provider",
            type="string",
            description="Provider: 'auto' (try all), 'replicate', 'fal', 'huggingface', 'comfyui'",
            required=False,
            default="auto",
            enum_values=["auto", "replicate", "fal", "huggingface", "comfyui"],
        ),
    ],
)
async def ai_video_generate(
    prompt: str,
    duration: int = 4,
    resolution: str = "720x480",
    model: str = "cogvideox-5b",
    provider: str = "auto",
) -> str:
    """
    Generate an AI video from a text prompt using open-source models.

    Fallback chain (auto mode):
      ComfyUI (local, free) → Fal.ai (free tier) → Replicate (trial credits) → HuggingFace (free)
    """
    if not prompt or not prompt.strip():
        return json.dumps({"error": "Prompt cannot be empty"})

    duration = max(1, min(duration, 10))
    prompt = prompt.strip()

    output_dir = _ensure_output_dir()
    output_file = output_dir / f"aivideo_{uuid.uuid4().hex[:12]}.mp4"

    logger.info(
        "[AIVideoGen] Starting | prompt='%.60s...' model=%s provider=%s duration=%ds",
        prompt, model, provider, duration,
    )

    # Collect available providers
    replicate_key = os.environ.get("REPLICATE_API_TOKEN", "")
    fal_key = os.environ.get("FAL_KEY", "")
    hf_key = os.environ.get("HF_TOKEN", "")

    providers_to_try: list[tuple[str, ...]] = []

    if provider == "auto":
        # Priority: local first (free), then cloud with free tiers
        providers_to_try.append(("comfyui",))
        if fal_key:
            providers_to_try.append(("fal", fal_key))
        if replicate_key:
            providers_to_try.append(("replicate", replicate_key))
        if hf_key:
            providers_to_try.append(("huggingface", hf_key))
        # If no API keys, still try ComfyUI local
        if not providers_to_try:
            providers_to_try.append(("comfyui",))
    elif provider == "comfyui":
        providers_to_try.append(("comfyui",))
    elif provider == "fal":
        if not fal_key:
            return json.dumps({"error": "FAL_KEY environment variable not set"})
        providers_to_try.append(("fal", fal_key))
    elif provider == "replicate":
        if not replicate_key:
            return json.dumps({"error": "REPLICATE_API_TOKEN environment variable not set"})
        providers_to_try.append(("replicate", replicate_key))
    elif provider == "huggingface":
        if not hf_key:
            return json.dumps({"error": "HF_TOKEN environment variable not set"})
        providers_to_try.append(("huggingface", hf_key))
    else:
        return json.dumps({"error": f"Unknown provider: {provider}"})

    if not providers_to_try:
        return json.dumps({
            "error": "No AI video providers available. Set at least one API key: "
                     "REPLICATE_API_TOKEN, FAL_KEY, HF_TOKEN, or run ComfyUI locally.",
            "help": {
                "replicate": "https://replicate.com/account/api-tokens (free trial credits)",
                "fal": "https://fal.ai/dashboard/keys (generous free tier)",
                "huggingface": "https://huggingface.co/settings/tokens (free)",
                "comfyui": "Install ComfyUI: https://github.com/comfyanonymous/ComfyUI",
            },
        })

    errors: list[str] = []
    start_time = time.time()

    for entry in providers_to_try:
        prov = entry[0]
        try:
            if prov == "comfyui":
                result = await _comfyui_generate(prompt, duration, resolution, output_file)
            elif prov == "fal":
                result = await _fal_generate(prompt, duration, resolution, model, entry[1], output_file)
            elif prov == "replicate":
                result = await _replicate_generate(prompt, duration, resolution, model, entry[1], output_file)
            elif prov == "huggingface":
                result = await _huggingface_generate(prompt, duration, model, entry[1], output_file)
            else:
                continue

            if "error" not in result and output_file.exists():
                elapsed = time.time() - start_time
                file_size = output_file.stat().st_size
                logger.info(
                    "[AIVideoGen] Success | provider=%s model=%s size=%.1fMB elapsed=%.1fs",
                    prov, model, file_size / 1_048_576, elapsed,
                )
                return json.dumps({
                    "status": "success",
                    "filepath": str(output_file),
                    "provider": result.get("provider", prov),
                    "model": result.get("model", model),
                    "duration_seconds": duration,
                    "resolution": resolution,
                    "file_size_mb": round(file_size / 1_048_576, 2),
                    "generation_time_seconds": round(elapsed, 1),
                    "prompt": prompt[:200],
                })

            error_msg = result.get("error", "Unknown error")
            errors.append(f"{prov}: {error_msg}")
            logger.warning("[AIVideoGen] Provider %s failed: %s", prov, error_msg)

        except httpx.HTTPStatusError as exc:
            errors.append(f"{prov}: HTTP {exc.response.status_code}")
            logger.warning("[AIVideoGen] Provider %s HTTP error: %s", prov, exc)
        except Exception as exc:
            errors.append(f"{prov}: {str(exc)[:200]}")
            logger.warning("[AIVideoGen] Provider %s error: %s", prov, exc)

    return json.dumps({
        "error": "All video generation providers failed",
        "tried": [e[0] for e in providers_to_try],
        "details": errors,
        "help": "Set API keys (REPLICATE_API_TOKEN, FAL_KEY, HF_TOKEN) or run ComfyUI locally",
    })
