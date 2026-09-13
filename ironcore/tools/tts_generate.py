"""
IronCore Tool: Text-to-Speech (TTS)
====================================
Generate speech audio from text.
Supports: ElevenLabs API, OpenAI TTS, and local Piper fallback.
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


def _ensure_output_dir() -> Path:
    p = Path(_OUTPUT_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


async def _elevenlabs_tts(text: str, voice_id: str, api_key: str, output_path: Path) -> dict:
    """Generate speech using ElevenLabs API."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)

    return {"provider": "elevenlabs", "voice_id": voice_id}


async def _openai_tts(text: str, voice: str, api_key: str, output_path: Path) -> dict:
    """Generate speech using OpenAI TTS API."""
    url = "https://api.openai.com/v1/audio/speech"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "tts-1",
        "input": text,
        "voice": voice,
        "response_format": "mp3",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)

    return {"provider": "openai", "voice": voice}


async def _piper_tts(text: str, output_path: Path, model: str = "en_US-lessac-medium") -> dict:
    """Generate speech using local Piper TTS (offline fallback)."""
    proc = await asyncio.create_subprocess_exec(
        "piper",
        "--model", model,
        "--output_file", str(output_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input=text.encode("utf-8")), timeout=60
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Piper failed: {stderr.decode()}")
    return {"provider": "piper", "model": model}


@skill(
    name="tts_generate",
    version="1.0.0",
    description="Convert text to speech audio. Returns the path to the generated audio file.",
    long_description=(
        "Multi-provider TTS. Priority: ElevenLabs (ELEVENLABS_API_KEY) → "
        "OpenAI (OPENAI_API_KEY) → Piper (local, offline). "
        "Supports multiple voices and output formats."
    ),
    author="brain",
    tags=["tts", "speech", "audio", "voice"],
    risk_level=RiskLevel.LOW,
    requires_network=True,
    estimated_latency_ms=5000.0,
    cost_tier="cheap",
    parameters=[
        SkillParameterSchema(name="text", type="string", description="Text to convert to speech", required=True),
        SkillParameterSchema(name="voice", type="string", description="Voice ID or name", required=False, default="default"),
        SkillParameterSchema(
            name="provider",
            type="string",
            description="TTS provider: 'auto', 'elevenlabs', 'openai', 'piper'",
            required=False,
            default="auto",
            enum_values=["auto", "elevenlabs", "openai", "piper"],
        ),
        SkillParameterSchema(
            name="output_format",
            type="string",
            description="Audio format: 'mp3' or 'wav'",
            required=False,
            default="mp3",
        ),
    ],
)
async def tts_generate(
    text: str,
    voice: str = "default",
    provider: str = "auto",
    output_format: str = "mp3",
) -> str:
    """Generate speech from text."""
    if not text.strip():
        return json.dumps({"error": "Text cannot be empty"})
    if len(text) > 5000:
        return json.dumps({"error": f"Text too long: {len(text)} chars (max 5000)"})

    output_dir = _ensure_output_dir()
    filename = f"tts_{uuid.uuid4().hex[:12]}.{output_format}"
    output_path = output_dir / filename

    elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    result = None
    errors = []

    # ElevenLabs
    if provider in ("auto", "elevenlabs") and elevenlabs_key:
        try:
            voice_id = voice if voice != "default" else "21m00Tcm4TlvDq8ikWAM"  # Rachel
            info = await _elevenlabs_tts(text, voice_id, elevenlabs_key, output_path)
            result = info
        except Exception as exc:
            errors.append(f"elevenlabs: {exc}")
            logger.warning("[tts] ElevenLabs failed: %s", exc)

    # OpenAI
    if result is None and provider in ("auto", "openai") and openai_key:
        try:
            oa_voice = voice if voice != "default" else "alloy"
            info = await _openai_tts(text, oa_voice, openai_key, output_path)
            result = info
        except Exception as exc:
            errors.append(f"openai: {exc}")
            logger.warning("[tts] OpenAI TTS failed: %s", exc)

    # Piper (local fallback)
    if result is None and provider in ("auto", "piper"):
        try:
            if output_format == "mp3":
                wav_path = output_path.with_suffix(".wav")
                info = await _piper_tts(text, wav_path)
                # Convert wav → mp3 if ffmpeg available
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-y", "-i", str(wav_path), "-q:a", "2", str(output_path),
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                    )
                    await asyncio.wait_for(proc.wait(), timeout=30)
                    wav_path.unlink(missing_ok=True)
                except Exception:
                    output_path = wav_path
                    output_format = "wav"
            else:
                info = await _piper_tts(text, output_path)
            result = info
        except Exception as exc:
            errors.append(f"piper: {exc}")
            logger.warning("[tts] Piper failed: %s", exc)

    if result is None:
        return json.dumps({
            "error": "All TTS providers failed",
            "details": errors,
            "hint": "Set ELEVENLABS_API_KEY or OPENAI_API_KEY, or install piper-tts locally.",
        })

    size = output_path.stat().st_size if output_path.exists() else 0
    return json.dumps({
        "status": "generated",
        "filepath": str(output_path),
        "format": output_format,
        "size_bytes": size,
        "text_length": len(text),
        **result,
    })
