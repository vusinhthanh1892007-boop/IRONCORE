"""
ironcore/api/stealth_routes.py — FastAPI routes for Stealth Browser control.

Endpoints:
    POST /v1/stealth/screenshot  — Navigate to URL, return base64 PNG screenshot
    POST /v1/stealth/scrape      — Navigate to URL, return page text content
    POST /v1/stealth/session/new — Create a new persistent stealth session
    DELETE /v1/stealth/session/{sid} — Close a stealth session
    GET  /v1/stealth/status      — List active sessions + stats
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/stealth", tags=["stealth"])

# ─── Active sessions store ────────────────────────────────────────────────────
# sid → {"browser": StealthBrowser, "page": Page, "created_at": float, "url": str}
_stealth_sessions: Dict[str, Dict[str, Any]] = {}
_stats = {"pages_visited": 0, "actions": 0}

# ─── Request / Response models ────────────────────────────────────────────────

_ALLOWED_SCHEMES = {"http", "https"}

def _validate_url(url: str) -> str:
    """Validate that the URL uses http/https (prevent SSRF to internal networks)."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"URL scheme '{parsed.scheme}' is not allowed. Use http or https.")
    # Block private IP ranges (basic SSRF protection)
    host = parsed.hostname or ""
    private_patterns = [
        r"^localhost$", r"^127\.", r"^10\.", r"^172\.(1[6-9]|2\d|3[01])\.",
        r"^192\.168\.", r"^::1$", r"^0\.0\.0\.0$",
    ]
    for pattern in private_patterns:
        if re.match(pattern, host, re.IGNORECASE):
            raise ValueError(f"Access to private/loopback addresses is not allowed.")
    return url


class ScreenshotRequest(BaseModel):
    url: str
    wait_ms: int = 1500     # ms to wait after navigation before screenshot
    full_page: bool = False
    session_id: str = ""    # reuse existing session; empty = create once-off

    class Config:
        # Validate on assignment
        validate_assignment = True


class ScrapeRequest(BaseModel):
    url: str
    selector: str = "body"  # CSS selector to extract content from
    session_id: str = ""

    class Config:
        validate_assignment = True


class ScreenshotResponse(BaseModel):
    success: bool
    url: str
    screenshot_b64: str = ""   # base64-encoded PNG
    error: str = ""
    elapsed_ms: float = 0


class ScrapeResponse(BaseModel):
    success: bool
    url: str
    text: str = ""
    html: str = ""
    error: str = ""
    elapsed_ms: float = 0


class SessionInfo(BaseModel):
    session_id: str
    url: str
    created_at: float


class StatusResponse(BaseModel):
    active_sessions: int
    pages_visited: int
    actions: int
    sessions: List[SessionInfo]


# ─── Browser factory ──────────────────────────────────────────────────────────

async def _get_or_create_browser() -> Any:
    """Create a StealthBrowser instance with a random fingerprint profile."""
    try:
        from ironcore.browser.stealth import StealthBrowser
        from ironcore.browser.fingerprint_spoofer import get_random_browser_profile
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Playwright (stealth browser) is not installed. "
                "Run: pip install playwright && playwright install chromium"
            ),
        )

    profile = get_random_browser_profile() if get_random_browser_profile else None
    browser = StealthBrowser(profile=profile)
    return browser


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/status")
async def stealth_status() -> StatusResponse:
    """Return the number of active stealth sessions and aggregate stats."""
    sessions = [
        SessionInfo(
            session_id=sid,
            url=info.get("url", ""),
            created_at=info.get("created_at", 0),
        )
        for sid, info in _stealth_sessions.items()
    ]
    return StatusResponse(
        active_sessions=len(_stealth_sessions),
        pages_visited=_stats["pages_visited"],
        actions=_stats["actions"],
        sessions=sessions,
    )


@router.post("/screenshot")
async def take_screenshot(body: ScreenshotRequest) -> ScreenshotResponse:
    """
    Navigate to ``url`` with the stealth browser and return a base64 PNG screenshot.

    Security: only http/https URLs are accepted; private IP ranges are blocked (SSRF prevention).
    """
    t0 = time.perf_counter()

    try:
        safe_url = _validate_url(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        browser = await _get_or_create_browser()
        async with browser:
            page = await browser.new_page()
            await page.goto(safe_url, wait_until="domcontentloaded")
            if body.wait_ms > 0:
                await asyncio.sleep(body.wait_ms / 1000)
            screenshot_bytes = await page.screenshot(full_page=body.full_page)

        _stats["pages_visited"] += 1
        _stats["actions"] += 1
        elapsed = (time.perf_counter() - t0) * 1000

        return ScreenshotResponse(
            success=True,
            url=safe_url,
            screenshot_b64=base64.b64encode(screenshot_bytes).decode(),
            elapsed_ms=round(elapsed, 1),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[Stealth] Screenshot failed for %s: %s", body.url, exc, exc_info=True)
        elapsed = (time.perf_counter() - t0) * 1000
        return ScreenshotResponse(
            success=False,
            url=body.url,
            error=str(exc),
            elapsed_ms=round(elapsed, 1),
        )


@router.post("/scrape")
async def scrape_page(body: ScrapeRequest) -> ScrapeResponse:
    """
    Navigate to ``url`` with the stealth browser and extract visible text / HTML.

    Returns plain text content via the specified CSS ``selector`` (default: body).
    """
    t0 = time.perf_counter()

    try:
        safe_url = _validate_url(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        browser = await _get_or_create_browser()
        async with browser:
            page = await browser.new_page()
            await page.goto(safe_url, wait_until="domcontentloaded")
            await asyncio.sleep(1.5)   # allow JS rendering

            selector = body.selector or "body"
            # Sanitize selector to avoid injection
            if len(selector) > 200 or "\n" in selector or ";" in selector:
                raise HTTPException(status_code=400, detail="Invalid CSS selector.")

            element = await page.query_selector(selector)
            text = ""
            html = ""
            if element:
                text = (await element.inner_text() or "").strip()
                html = (await element.inner_html() or "").strip()

        _stats["pages_visited"] += 1
        _stats["actions"] += 1
        elapsed = (time.perf_counter() - t0) * 1000

        return ScrapeResponse(
            success=True,
            url=safe_url,
            text=text[:8000],   # cap at 8KB to avoid huge payloads
            html=html[:16000],
            elapsed_ms=round(elapsed, 1),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[Stealth] Scrape failed for %s: %s", body.url, exc, exc_info=True)
        elapsed = (time.perf_counter() - t0) * 1000
        return ScrapeResponse(
            success=False,
            url=body.url,
            error=str(exc),
            elapsed_ms=round(elapsed, 1),
        )
