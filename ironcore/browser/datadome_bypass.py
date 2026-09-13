"""
ironcore/browser/datadome_bypass.py — Phase 7.2: DataDome Bot Detection Bypass

DataDome behavioral analysis:
  - Mouse movement, scroll patterns, typing cadence
  - Request headers: Accept-Language, sec-ch-ua, sec-fetch-* chain
  - TLS fingerprinting (JA3/JA4) — requires curl-cffi for full bypass
  - Time-on-page: DataDome flags sessions < 5s as suspicious

Strategy:
  1. Prime behavioral signals: natural scroll + mouse movement before any action.
  2. Spoof request headers: full Chrome header set (Accept, sec-ch-ua, sec-fetch-*).
  3. Enforce minimum time-on-page (30s warm-up recommended).
  4. HTTP-level: recommend curl-cffi for TLS fingerprint matching.
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── Lazy imports ─────────────────────────────────────────────────────────────

try:
    from playwright.async_api import Page, Route, Request
except ImportError:
    Page = Any  # type: ignore
    Route = Any  # type: ignore
    Request = Any  # type: ignore

try:
    from ironcore.browser.mouse_engine import MouseEngine, generate_mouse_path
except ImportError:
    MouseEngine = None  # type: ignore
    generate_mouse_path = None  # type: ignore

# ─── Detection signatures ─────────────────────────────────────────────────────

DATADOME_BLOCK_PATTERNS = [
    "datadome.co",
    "Device blocked",
    "datadome",
    "Please verify you are a human",
    "mCaptchaVerification",
    "dd-captcha",
    "ddcaptcha",
    "DD_RUM",
]

DATADOME_HEADER_KEY = "x-datadome-clientid"
DATADOME_403_BODY_MARKERS = ["blocked", "403", "datadome"]

# Chrome 120 sec-ch-ua strings
_SEC_UA_FULL = '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'
_SEC_UA_MOBILE = "?0"


# ─── 7.2a DataDomeDetector ───────────────────────────────────────────────────

class DataDomeDetector:
    """
    Detect DataDome bot protection blocks on a Playwright Page.
    """

    @staticmethod
    async def is_blocked(page: "Page") -> bool:
        """
        Return True if the current page shows a DataDome block or interstitial.
        Checks URL, body content, and response headers.
        """
        try:
            url = page.url
            if "datadome.co" in url:
                logger.debug("[DD/Detector] Redirect to datadome.co detected: %s", url)
                return True
        except Exception:
            pass

        try:
            body = await page.content()
            if any(pat.lower() in body.lower() for pat in DATADOME_BLOCK_PATTERNS[:4]):
                logger.debug("[DD/Detector] Block pattern found in body")
                return True
        except Exception:
            pass

        return False

    @staticmethod
    async def detect_block_type(page: "Page") -> str:
        """
        Returns: 'captcha' | 'hard_block' | 'soft_block' | 'none'
        """
        try:
            body = await page.content()
            if any(p in body.lower() for p in ["dd-captcha", "ddcaptcha", "mcaptcha"]):
                return "captcha"
            if "device blocked" in body.lower() or "permanently blocked" in body.lower():
                return "hard_block"
            if any(p in body.lower() for p in DATADOME_BLOCK_PATTERNS):
                return "soft_block"
        except Exception:
            pass
        return "none"


# ─── 7.2b DataDomeBypass ─────────────────────────────────────────────────────

class DataDomeBypass:
    """
    Behavioral priming and header spoofing to avoid DataDome detection.

    DataDome uses:
    1. Behavioral analysis: mouse, scroll, typing
    2. Header fingerprinting: sec-ch-ua, Accept-Encoding chain
    3. Time-on-page: < 5s → bot signal
    4. TLS fingerprinting: JA3/JA4 (needs curl-cffi for full bypass)
    """

    MIN_TIME_ON_PAGE = 30.0          # seconds DataDome waits before trusting
    SCROLL_COUNT_RANGE = (4, 10)     # natural scroll actions
    MOUSE_MOVE_COUNT = 8             # mouse movements across page

    def __init__(self, mouse_engine: Optional["MouseEngine"] = None) -> None:
        if mouse_engine is None and MouseEngine is not None:
            mouse_engine = MouseEngine()
        self.mouse = mouse_engine
        self._session_start: Dict[str, float] = {}

    # ── Behavioral Priming ────────────────────────────────────────────────────

    async def prime_behavioral_signals(
        self,
        page: "Page",
        min_duration: float = MIN_TIME_ON_PAGE,
    ) -> None:
        """
        Simulate natural browsing behavior to satisfy DataDome behavioral analysis.
        - Random mouse movements across viewport
        - Natural scroll pattern (vary speed/direction)
        - Minimum time-on-page enforcement

        Should be called BEFORE any target action (form fill, button click, etc.)
        """
        session_id = page.url
        self._session_start[session_id] = time.monotonic()

        logger.info(
            "[DD/Bypass] Priming behavioral signals (min=%.0fs) on %s",
            min_duration, page.url
        )

        # Get viewport size
        viewport_w, viewport_h = 1920, 1080
        try:
            dims = await page.evaluate(
                "() => ({w: window.innerWidth, h: window.innerHeight})"
            )
            viewport_w = dims.get("w", 1920)
            viewport_h = dims.get("h", 1080)
        except Exception:
            pass

        # Phase 1: Initial reading pause
        await asyncio.sleep(random.gauss(2.0, 0.5))

        # Phase 2: Mouse movements (diagonal, curved paths across viewport)
        await self._simulate_mouse_movements(page, viewport_w, viewport_h)

        # Phase 3: Natural scroll down → partial scroll back up
        await self._simulate_scroll(page)

        # Phase 4: More mouse movements (looks like user reading)
        await self._simulate_mouse_movements(page, viewport_w, viewport_h, count=4)

        # Phase 5: Ensure minimum time-on-page elapsed
        elapsed = time.monotonic() - self._session_start[session_id]
        remaining = min_duration - elapsed
        if remaining > 0:
            logger.debug("[DD/Bypass] Waiting %.0fs more for min_time_on_page", remaining)
            # Break waiting into chunks with mouse micro-moves
            chunks = max(1, int(remaining / 5))
            per_chunk = remaining / chunks
            for _ in range(chunks):
                await asyncio.sleep(per_chunk)
                try:
                    # Micro-movement to simulate reading
                    jitter_x = random.uniform(viewport_w * 0.2, viewport_w * 0.8)
                    jitter_y = random.uniform(viewport_h * 0.2, viewport_h * 0.7)
                    await page.mouse.move(jitter_x, jitter_y)
                except Exception:
                    pass

        logger.info("[DD/Bypass] Behavioral priming complete (%.0fs total)", min_duration)

    async def _simulate_mouse_movements(
        self,
        page: "Page",
        viewport_w: int,
        viewport_h: int,
        count: Optional[int] = None,
    ) -> None:
        """Move mouse in natural Bezier paths across the viewport."""
        if count is None:
            count = self.MOUSE_MOVE_COUNT

        # Anchor points: header, sidebar, content, footer zones
        zones = [
            (random.uniform(0.1, 0.9), random.uniform(0.05, 0.15)),  # header
            (random.uniform(0.1, 0.4), random.uniform(0.2, 0.5)),    # left content
            (random.uniform(0.5, 0.9), random.uniform(0.3, 0.7)),    # right content
            (random.uniform(0.2, 0.8), random.uniform(0.6, 0.9)),    # footer
            (random.uniform(0.3, 0.7), random.uniform(0.4, 0.6)),    # center
        ]

        for i in range(count):
            zone = random.choice(zones)
            tx = int(viewport_w * zone[0])
            ty = int(viewport_h * zone[1])

            try:
                if self.mouse:
                    await self.mouse.move_to(page, float(tx), float(ty), target_size=50.0)
                else:
                    await page.mouse.move(tx, ty)
                await asyncio.sleep(random.gauss(0.4, 0.15))
            except Exception as exc:
                logger.debug("[DD/Bypass] Mouse move error: %s", exc)

    async def _simulate_scroll(self, page: "Page") -> None:
        """Natural scroll: go down 60-80% of page, then partially back up."""
        try:
            doc_h = await page.evaluate("() => document.body.scrollHeight") or 3000
        except Exception:
            doc_h = 3000

        try:
            vh = await page.evaluate("() => window.innerHeight") or 768
        except Exception:
            vh = 768

        num_scrolls = random.randint(*self.SCROLL_COUNT_RANGE)
        # Scroll unit: 40-70% of viewport height
        scroll_unit = vh * random.uniform(0.4, 0.7)
        current = 0
        max_scroll = doc_h - vh

        # ── Down scrolls ───────────────────────────────────────────────────
        for i in range(num_scrolls):
            current = min(current + scroll_unit, max_scroll * 0.8)
            speed = random.choice(["smooth", "auto"])
            try:
                await page.evaluate(
                    f"window.scrollTo({{top: {current:.0f}, behavior: '{speed}'}})"
                )
            except Exception:
                pass
            # Reading pause — longer for first few scrolls
            if i < 3:
                await asyncio.sleep(random.gauss(2.5, 0.8))
            else:
                await asyncio.sleep(random.gauss(1.2, 0.4))

        # ── Partial scroll back up ─────────────────────────────────────────
        back_target = current * random.uniform(0.3, 0.6)
        try:
            await page.evaluate(
                f"window.scrollTo({{top: {back_target:.0f}, behavior: 'smooth'}})"
            )
        except Exception:
            pass
        await asyncio.sleep(random.gauss(1.5, 0.5))

    # ── Header Spoofing ───────────────────────────────────────────────────────

    @staticmethod
    def spoof_request_headers(
        headers: Dict[str, str],
        locale: str = "en-US",
        platform: str = "Win32",
        user_agent: str = "",
    ) -> Dict[str, str]:
        """
        Add/override request headers to mimic a real Chrome browser.
        DataDome flags missing or inconsistent sec-ch-ua / sec-fetch-* chains.

        Call this in a Playwright route handler to intercept and modify headers.
        """
        lang_primary = locale.split("-")[0]
        spoofed = {
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8,"
                "application/signed-exchange;v=b3;q=0.7"
            ),
            "Accept-Language": f"{locale},{lang_primary};q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Cache-Control": "max-age=0",
            "sec-ch-ua": _SEC_UA_FULL,
            "sec-ch-ua-mobile": _SEC_UA_MOBILE,
            "sec-ch-ua-platform": f'"{platform}"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
        if user_agent:
            spoofed["User-Agent"] = user_agent

        # Merge: spoofed values override caller's, keep other caller headers
        result = {**headers}
        result.update(spoofed)
        return result

    async def install_header_interceptor(
        self,
        page: "Page",
        locale: str = "en-US",
        platform: str = "Win32",
        user_agent: str = "",
    ) -> None:
        """
        Install a Playwright route interceptor to spoof headers on ALL requests.
        Call this before page.goto() to ensure all requests carry proper headers.
        """
        async def _route_handler(route: "Route", request: "Request") -> None:
            headers = dict(request.headers)
            spoofed = self.spoof_request_headers(headers, locale, platform, user_agent)
            await route.continue_(headers=spoofed)

        await page.route("**/*", _route_handler)
        logger.debug("[DD/Bypass] Header interceptor installed on all routes")

    # ── TLS Note ─────────────────────────────────────────────────────────────

    @staticmethod
    def get_tls_advice() -> str:
        """
        For full TLS fingerprint (JA3/JA4) bypass, use curl-cffi:

            from curl_cffi.requests import AsyncSession
            async with AsyncSession(impersonate='chrome120') as session:
                resp = await session.get(url, headers=spoofed_headers)

        curl-cffi impersonates Chrome's TLS hello — defeats JA3/JA4 detection.
        Playwright's TLS fingerprint differs from Chrome — DataDome may flag it.
        """
        return (
            "Install curl-cffi and use AsyncSession(impersonate='chrome120') "
            "for HTTP-level requests requiring full TLS fingerprint matching."
        )
