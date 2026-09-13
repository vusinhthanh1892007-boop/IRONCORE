"""
IronCore Tool: Media Transcription
===================================
Transcribe audio/video files to text.
Supports: OpenAI Whisper API, local whisper (whisper.cpp / faster-whisper).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

import httpx

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


async def _openai_transcribe(filepath: Path, api_key: str, language: Optional[str]) -> dict:
    """Transcribe using OpenAI Whisper API."""
    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=120) as client:
        with open(filepath, "rb") as f:
            files = {"file": (filepath.name, f, "audio/mpeg")}
            data = {"model": "whisper-1", "response_format": "verbose_json"}
            if language:
                data["language"] = language
            resp = await client.post(url, headers=headers, files=files, data=data)
            resp.raise_for_status()
            result = resp.json()

    return {
        "provider": "openai_whisper",
        "text": result.get("text", ""),
        "language": result.get("language"),
        "duration": result.get("duration"),
        "segments": [
            {"start": s["start"], "end": s["end"], "text": s["text"]}
            for s in result.get("segments", [])
        ],
    }


async def _local_whisper_transcribe(filepath: Path, model: str, language: Optional[str]) -> dict:
    """Transcribe using local whisper installation."""
    args = [
        "whisper", str(filepath),
        "--model", model,
        "--output_format", "json",
        "--output_dir", str(filepath.parent),
    ]
    if language:
        args.extend(["--language", language])

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)

    if proc.returncode != 0:
        raise RuntimeError(f"Whisper failed: {stderr.decode()}")

    json_path = filepath.with_suffix(".json")
    if json_path.exists():
        import json as _json
        data = _json.loads(json_path.read_text())
        return {
            "provider": "local_whisper",
            "text": data.get("text", ""),
            "language": data.get("language"),
            "segments": [
                {"start": s["start"], "end": s["end"], "text": s["text"]}
                for s in data.get("segments", [])
            ],
        }

    return {
        "provider": "local_whisper",
        "text": stdout.decode("utf-8", errors="replace"),
        "language": language,
        "segments": [],
    }


@skill(
    name="media_transcribe",
    version="1.0.0",
    description="Transcribe audio or video files to text with timestamps.",
    long_description=(
        "Multi-provider media transcription. Uses OpenAI Whisper API when "
        "OPENAI_API_KEY is set, falls back to local whisper installation. "
        "Supports mp3, wav, mp4, webm, m4a, and more."
    ),
    author="brain",
    tags=["transcription", "audio", "video", "speech-to-text", "whisper"],
    risk_level=RiskLevel.LOW,
    requires_network=True,
    estimated_latency_ms=30000.0,
    cost_tier="cheap",
    parameters=[
        SkillParameterSchema(name="filepath", type="string", description="Path to audio/video file", required=True),
        SkillParameterSchema(name="language", type="string", description="Language code (e.g. 'en', 'vi', 'ja'). Auto-detect if omitted.", required=False),
        SkillParameterSchema(
            name="provider",
            type="string",
            description="'auto', 'openai', or 'local'",
            required=False,
            default="auto",
            enum_values=["auto", "openai", "local"],
        ),
        SkillParameterSchema(name="model", type="string", description="Local whisper model: 'tiny', 'base', 'small', 'medium', 'large'", required=False, default="base"),
    ],
)
async def media_transcribe(
    filepath: str,
    language: Optional[str] = None,
    provider: str = "auto",
    model: str = "base",
) -> str:
    """Transcribe audio/video to text."""
    path = Path(filepath)
    if not path.exists():
        return json.dumps({"error": f"File not found: {filepath}"})
    if path.stat().st_size > _MAX_FILE_SIZE:
        return json.dumps({"error": f"File too large: {path.stat().st_size} bytes (max {_MAX_FILE_SIZE})"})

    openai_key = os.environ.get("OPENAI_API_KEY")
    errors = []

    # OpenAI Whisper API
    if provider in ("auto", "openai") and openai_key:
        try:
            result = await _openai_transcribe(path, openai_key, language)
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            errors.append(f"openai: {exc}")
            logger.warning("[transcribe] OpenAI Whisper failed: %s", exc)

    # Local whisper
    if provider in ("auto", "local"):
        try:
            result = await _local_whisper_transcribe(path, model, language)
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            errors.append(f"local: {exc}")
            logger.warning("[transcribe] Local whisper failed: %s", exc)

    return json.dumps({
        "error": "All transcription providers failed",
        "details": errors,
        "hint": "Set OPENAI_API_KEY or install whisper locally (pip install openai-whisper).",
    })
