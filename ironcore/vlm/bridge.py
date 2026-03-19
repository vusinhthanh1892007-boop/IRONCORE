"""
IronCore: VLM Bridge — Vision-Language Model Integration
=========================================================

Connects IronCore's CAPTCHA solving pipeline to a Vision-Language Model.

Supported backends:
  OLLAMA   — Local LLaVA / bakllava / gemma3-vision via Ollama REST API
             (free, private, zero data leakage)
  OPENAI   — GPT-4V / GPT-4o via OpenAI Vision API (cloud, paid)
  DISABLED — No-op fallback that returns low-confidence empty result

The Ghost (Gemini) calls analyze_captcha() with a Base64 screenshot.
This module sends it to the VLM, parses back coordinates, and returns
a structured VLMAnalysisResult.

Interface contract (used by captcha_solver.py and ghost_agent.py):
    result = await bridge.analyze_captcha(
        image_base64="<base64 PNG/JPEG string>",
        captcha_type="recaptcha_v2",
        instruction="Select all images containing traffic lights",
    )

Author: The Brain (IronCore Project — VLM Phase)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Types / Enums
# ─────────────────────────────────────────────────────────────

class CaptchaType(str, Enum):
    RECAPTCHA_V2   = "recaptcha_v2"   # Image grid selection
    RECAPTCHA_V3   = "recaptcha_v3"   # Score-based (no image needed)
    GEETEST        = "geetest"        # Slider puzzle — returns X offset
    FUNCAPTCHA     = "funcaptcha"     # Rotation / object game
    HCAPTCHA       = "hcaptcha"       # Image grid (similar to reCAPTCHA v2)
    DATADOME       = "datadome"       # Bot detection page
    CLOUDFLARE     = "cloudflare"     # Turnstile / 5-second shield
    GENERIC        = "generic"        # Unknown — describe-and-click


class VLMBackend(str, Enum):
    OLLAMA   = "ollama"    # Local Ollama REST API
    OPENAI   = "openai"    # OpenAI Vision (GPT-4V / GPT-4o)
    DISABLED = "disabled"  # No-op, always returns low-confidence result


# ─────────────────────────────────────────────────────────────
# Result Model
# ─────────────────────────────────────────────────────────────

class VLMAnalysisResult(BaseModel):
    """Structured output from the VLM after analyzing a CAPTCHA screenshot."""

    captcha_type:  str                        = Field(description="CaptchaType value")
    coordinates:   List[Tuple[int, int]]      = Field(default_factory=list,
                                                      description="(x, y) click targets in px")
    slider_offset: Optional[float]            = Field(default=None,
                                                      description="X-axis slide distance for GeeTest (px)")
    confidence:    float                      = Field(default=0.0, ge=0.0, le=1.0)
    reasoning:     str                        = Field(default="")
    raw_response:  str                        = Field(default="")
    backend_used:  str                        = Field(default="")
    latency_ms:    float                      = Field(default=0.0)


# ─────────────────────────────────────────────────────────────
# Coordinate / Offset Parsing
# ─────────────────────────────────────────────────────────────

_COORD_PATTERNS = [
    # JSON array: [[120,230],[400,310]]  or  [[120, 230]]
    re.compile(r'\[\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]', re.DOTALL),
    # Python tuple style: (120, 230)
    re.compile(r'\(\s*(\d+)\s*,\s*(\d+)\s*\)'),
    # x=120, y=230  or  x: 120, y: 230
    re.compile(r'x\s*[=:]\s*(\d+)[,\s]+y\s*[=:]\s*(\d+)', re.IGNORECASE),
    # center: 120, 230
    re.compile(r'center[:\s]+(\d+)[,\s]+(\d+)', re.IGNORECASE),
]

_OFFSET_PATTERNS = [
    # offset: 215  /  slide 215  /  distance: 215
    re.compile(r'(?:offset|slide|distance|drag)[:\s]+(\d+(?:\.\d+)?)', re.IGNORECASE),
    # x_offset = 215
    re.compile(r'x_offset\s*[=:]\s*(\d+(?:\.\d+)?)', re.IGNORECASE),
    # A standalone number at end of response (last resort)
    re.compile(r'\b(\d{2,3}(?:\.\d+)?)\b'),
]


def _parse_coordinates(text: str) -> List[Tuple[int, int]]:
    """Extract all (x, y) coordinate pairs from free-form VLM response text."""
    coords: List[Tuple[int, int]] = []
    seen: set = set()
    for pat in _COORD_PATTERNS:
        for m in pat.finditer(text):
            pair = (int(m.group(1)), int(m.group(2)))
            if pair not in seen:
                seen.add(pair)
                coords.append(pair)
    return coords


def _parse_slider_offset(text: str) -> Optional[float]:
    """Extract a slider X-offset value from VLM response text."""
    for pat in _OFFSET_PATTERNS:
        m = pat.search(text)
        if m:
            val = float(m.group(1))
            # Sanity: slider offsets are typically 10–400 px
            if 5.0 <= val <= 500.0:
                return val
    return None


def _estimate_confidence(text: str, coords: List[Tuple[int, int]],
                          offset: Optional[float]) -> float:
    """Heuristic confidence from response richness."""
    score = 0.0
    if coords or offset is not None:
        score += 0.5
    lower = text.lower()
    positive_words = ["found", "detected", "identified", "located", "confident",
                      "traffic", "crosswalk", "bicycle", "vehicle", "object"]
    negative_words = ["unsure", "cannot", "unable", "unclear", "no image",
                      "not visible", "sorry", "apologize"]
    score += min(0.3, sum(0.05 for w in positive_words if w in lower))
    score -= min(0.4, sum(0.1  for w in negative_words if w in lower))
    return max(0.0, min(1.0, round(score, 2)))


# ─────────────────────────────────────────────────────────────
# Prompt Templates
# ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are a precise visual analysis assistant. "
    "Analyze the provided screenshot and respond ONLY with the requested "
    "coordinates or values in the exact format specified. "
    "Do NOT include disclaimers, apologies, or extra text."
)

_GRID_INSTRUCTION = (
    "{instruction}\n\n"
    "Return the center (x, y) pixel coordinates (e.g. (120, 230)) for every "
    "matching cell. If multiple cells match, list ALL of them one per line. "
    "If nothing matches, write: NO_MATCH"
)

_SLIDER_INSTRUCTION = (
    "This is a GeeTest slider puzzle. Find the exact pixel distance (X offset) "
    "needed to drag the puzzle piece from its current position to fill the gap "
    "in the background image.\n"
    "Respond with a single integer or decimal number representing the pixel offset. "
    "Example: 215"
)

_GENERIC_INSTRUCTION = (
    "{instruction}\n\n"
    "Return the (x, y) coordinates of the target. Example: (120, 230)"
)


def _build_prompt(captcha_type: str, instruction: str) -> str:
    if captcha_type in (CaptchaType.GEETEST, "geetest"):
        return _SLIDER_INSTRUCTION
    if captcha_type in (CaptchaType.RECAPTCHA_V2, CaptchaType.HCAPTCHA,
                        "recaptcha_v2", "hcaptcha"):
        return _GRID_INSTRUCTION.format(instruction=instruction)
    return _GENERIC_INSTRUCTION.format(instruction=instruction)


# ─────────────────────────────────────────────────────────────
# VLMBridge
# ─────────────────────────────────────────────────────────────

class VLMBridgeError(Exception):
    """Raised when the VLM backend returns an unrecoverable error."""


class VLMBridge:
    """
    Async Vision-Language Model bridge supporting Ollama and OpenAI backends.

    Usage:
        bridge = VLMBridge.from_env()       # auto-detect from env vars
        result = await bridge.analyze_captcha(
            image_base64="<base64>",
            captcha_type="geetest",
            instruction="Find the X offset to complete the slider puzzle",
        )
    """

    def __init__(
        self,
        api_endpoint: str = "http://localhost:11434/api/generate",
        model: str = "llava:13b",
        backend: VLMBackend = VLMBackend.OLLAMA,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        openai_api_key: Optional[str] = None,
    ) -> None:
        self.api_endpoint    = api_endpoint
        self.model           = model
        self.backend         = backend
        self.timeout_seconds = timeout_seconds
        self.max_retries     = max_retries
        self._openai_api_key = openai_api_key or os.environ.get("OPENAI_API_KEY", "")
        self._client: Optional[httpx.AsyncClient] = None
        logger.info(
            "[VLMBridge] Initialized | backend=%s model=%s endpoint=%s",
            backend.value, model, api_endpoint,
        )

    @classmethod
    def from_env(cls) -> "VLMBridge":
        """Create a VLMBridge from environment variables.

        Env vars:
            IRONCORE_VLM_BACKEND   — "ollama" | "openai" | "disabled"  (default: ollama)
            IRONCORE_VLM_ENDPOINT  — Ollama API URL (default: http://localhost:11434/api/generate)
            IRONCORE_VLM_MODEL     — Model tag (default: llava:13b)
            IRONCORE_VLM_TIMEOUT   — Request timeout in seconds (default: 30)
            OPENAI_API_KEY         — Required when backend=openai
        """
        backend_raw = os.environ.get("IRONCORE_VLM_BACKEND", "ollama").lower()
        try:
            backend = VLMBackend(backend_raw)
        except ValueError:
            logger.warning("[VLMBridge] Unknown backend '%s', using DISABLED", backend_raw)
            backend = VLMBackend.DISABLED

        return cls(
            api_endpoint=os.environ.get(
                "IRONCORE_VLM_ENDPOINT", "http://localhost:11434/api/generate"
            ),
            model=os.environ.get("IRONCORE_VLM_MODEL", "llava:13b"),
            backend=backend,
            timeout_seconds=float(os.environ.get("IRONCORE_VLM_TIMEOUT", "30")),
            max_retries=int(os.environ.get("IRONCORE_VLM_MAX_RETRIES", "2")),
        )

    # ── HTTP client lifecycle ────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "VLMBridge":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ── Health Check ─────────────────────────────────────────

    async def health_check(self) -> bool:
        """Return True if the VLM backend is reachable."""
        if self.backend == VLMBackend.DISABLED:
            return False
        try:
            client = await self._get_client()
            if self.backend == VLMBackend.OLLAMA:
                base = self.api_endpoint.rsplit("/api/", 1)[0]
                resp = await client.get(f"{base}/api/tags", timeout=5.0)
                return resp.status_code == 200
            if self.backend == VLMBackend.OPENAI:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {self._openai_api_key}"},
                    timeout=5.0,
                )
                return resp.status_code == 200
        except Exception as exc:
            logger.debug("[VLMBridge] health_check failed: %s", exc)
        return False

    # ── Backend Calls ─────────────────────────────────────────

    async def _call_ollama(self, prompt: str, image_base64: str) -> str:
        """POST to Ollama /api/generate with the image and return the text response."""
        client = await self._get_client()
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": f"{_SYSTEM_PROMPT}\n\n{prompt}",
            "images": [image_base64],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 256},
        }
        resp = await client.post(self.api_endpoint, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")

    async def _call_openai(self, prompt: str, image_base64: str) -> str:
        """POST to OpenAI Chat Completions with vision (GPT-4o / gpt-4-vision-preview)."""
        client = await self._get_client()
        # Detect image format from magic bytes prefix (PNG header check)
        media_type = "image/png" if image_base64.startswith("iVBOR") else "image/jpeg"
        payload: Dict[str, Any] = {
            "model": self.model or "gpt-4o",
            "max_tokens": 256,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{image_base64}",
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
        }
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self._openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    # ── Public API ────────────────────────────────────────────

    async def analyze_captcha(
        self,
        image_base64: str,
        captcha_type: str = CaptchaType.GENERIC,
        instruction: str = "Identify and return the target coordinates.",
    ) -> VLMAnalysisResult:
        """
        Analyze a CAPTCHA screenshot with the configured VLM backend.

        Args:
            image_base64: Base64-encoded PNG or JPEG screenshot (no data:// prefix).
            captcha_type: One of CaptchaType enum values (or raw string).
            instruction:  Human-readable instruction, e.g. "Select all traffic lights".

        Returns:
            VLMAnalysisResult with coordinates/offset and confidence score.
        """
        if self.backend == VLMBackend.DISABLED:
            logger.debug("[VLMBridge] Backend DISABLED — returning empty result")
            return VLMAnalysisResult(
                captcha_type=captcha_type,
                confidence=0.0,
                reasoning="VLM backend is disabled.",
                backend_used="disabled",
            )

        prompt = _build_prompt(captcha_type, instruction)
        raw_text = ""
        t0 = time.perf_counter()
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 2):
            try:
                if self.backend == VLMBackend.OLLAMA:
                    raw_text = await self._call_ollama(prompt, image_base64)
                elif self.backend == VLMBackend.OPENAI:
                    raw_text = await self._call_openai(prompt, image_base64)
                last_exc = None
                break
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "[VLMBridge] HTTP %s on attempt %d/%d: %s",
                    exc.response.status_code, attempt, self.max_retries + 1, exc,
                )
                last_exc = exc
                if exc.response.status_code in (400, 401, 403, 404):
                    break  # Non-retryable
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning(
                    "[VLMBridge] Network error on attempt %d/%d: %s",
                    attempt, self.max_retries + 1, exc,
                )
                last_exc = exc
                if attempt < self.max_retries + 1:
                    await asyncio.sleep(1.0 * attempt)

        latency = (time.perf_counter() - t0) * 1000

        if last_exc is not None and not raw_text:
            logger.error("[VLMBridge] All %d attempts failed: %s", self.max_retries + 1, last_exc)
            return VLMAnalysisResult(
                captcha_type=captcha_type,
                confidence=0.0,
                reasoning=f"Backend error after {self.max_retries + 1} attempts: {last_exc}",
                raw_response="",
                backend_used=self.backend.value,
                latency_ms=round(latency, 1),
            )

        # Parse response
        coords = _parse_coordinates(raw_text)
        offset = _parse_slider_offset(raw_text) if captcha_type in (
            CaptchaType.GEETEST, "geetest") else None
        confidence = _estimate_confidence(raw_text, coords, offset)

        logger.info(
            "[VLMBridge] Done | type=%s coords=%s offset=%s conf=%.2f latency=%.0fms",
            captcha_type, coords, offset, confidence, latency,
        )

        return VLMAnalysisResult(
            captcha_type=captcha_type,
            coordinates=coords,
            slider_offset=offset,
            confidence=confidence,
            reasoning=raw_text[:500],
            raw_response=raw_text,
            backend_used=self.backend.value,
            latency_ms=round(latency, 1),
        )


# ─────────────────────────────────────────────────────────────
# Smoke test
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    async def _smoke_test() -> None:
        bridge = VLMBridge.from_env()
        is_healthy = await bridge.health_check()
        print(f"[VLMBridge] health_check → {is_healthy}")

        # Tiny 1×1 white PNG as a minimal test image
        _TINY_PNG_B64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="
        )
        result = await bridge.analyze_captcha(
            image_base64=_TINY_PNG_B64,
            captcha_type=CaptchaType.RECAPTCHA_V2,
            instruction="Select all images with traffic lights",
        )
        print(f"[VLMBridge] Result: {result.model_dump_json(indent=2)}")
        await bridge.close()

    asyncio.run(_smoke_test())
