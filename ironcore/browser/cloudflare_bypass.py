"""
ironcore/browser/cloudflare_bypass.py — Phase 7.1: Cloudflare Bot Management Bypass

Cloudflare bot protection layers:
  JS Challenge  — CF injects JS fingerprinting, issues cf_clearance cookie
  Turnstile     — visual CAPTCHA widget (iframe-based), click-to-solve
  Rate Limit    — IP/fingerprint-based 429 or 403 with Retry-After

Strategy:
  1. Auto-wait: Playwright executes CF JS → cf_clearance set automatically (most cases)
  2. Turnstile: locate iframe → MouseEngine click checkbox → wait for token
  3. Retry: up to 3 attempts, rotate profile between retries
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── Lazy imports ─────────────────────────────────────────────────────────────

try:
    from playwright.async_api import Page, Frame, Response
except ImportError:
    Page = Any  # type: ignore
    Frame = Any  # type: ignore
    Response = Any  # type: ignore

try:
    from ironcore.browser.mouse_engine import MouseEngine
except ImportError:
    MouseEngine = None  # type: ignore

# ─── Selectors ────────────────────────────────────────────────────────────────

CF_TITLE_PATTERNS = [
    "Just a moment",
    "Checking your browser",
    "DDoS protection by Cloudflare",
    "Please wait",
]

CF_CHALLENGE_BODY_PATTERNS = [
    "cf-browser-verification",
    "cf_challenge_running",
    "cf-spinner",
    "__cf_chl",
]

CF_TURNSTILE_SELECTORS = [
    "iframe[src*='challenges.cloudflare.com']",
    "iframe[src*='turnstile']",
    "div.cf-turnstile",
    "[id*='turnstile']",
]

CF_SUCCESS_COOKIE = "cf_clearance"
CF_TURNSTILE_CHECKBOX = "input[type='checkbox']"


# ─── 7.1a CloudflareDetector ──────────────────────────────────────────────────

class CloudflareDetector:
    """
    Detect Cloudflare protection challenges on a Playwright Page.
    """

    @staticmethod
    async def is_cloudflare_challenge(page: "Page") -> bool:
        """
        Return True if the current page is a Cloudflare challenge page.
        Checks title, body content, and response headers.
        """
        try:
            title = await page.title()
            if any(p.lower() in title.lower() for p in CF_TITLE_PATTERNS):
                logger.debug("[CF/Detector] Challenge detected via title: '%s'", title)
                return True
        except Exception:
            pass

        try:
            body = await page.content()
            if any(pat in body for pat in CF_CHALLENGE_BODY_PATTERNS):
                logger.debug("[CF/Detector] Challenge detected via body pattern")
                return True
        except Exception:
            pass

        # Check for cf_clearance absence + 403/503
        try:
            url = page.url
            if "__cf_chl" in url or "cdn-cgi/challenge-platform" in url:
                return True
        except Exception:
            pass

        return False

    @staticmethod
    async def detect_challenge_type(page: "Page") -> str:
        """
        Classify the Cloudflare challenge type.
        Returns: 'js_challenge' | 'turnstile' | 'rate_limit' | 'none'
        """
        # Turnstile check first — has iframe
        try:
            for sel in CF_TURNSTILE_SELECTORS:
                elem = await page.query_selector(sel)
                if elem:
                    logger.debug("[CF/Detector] Turnstile detected via selector: %s", sel)
                    return "turnstile"
        except Exception:
            pass

        # Rate limit check — HTTP 429 or Retry-After
        try:
            body = await page.content()
            if "error code: 429" in body.lower() or "rate limit" in body.lower():
                return "rate_limit"
            if "error code: 1020" in body.lower():
                return "rate_limit"
        except Exception:
            pass

        # JS challenge (default CF protection)
        try:
            title = await page.title()
            body = await page.content()
            if any(p.lower() in title.lower() for p in CF_TITLE_PATTERNS) or \
               any(pat in body for pat in CF_CHALLENGE_BODY_PATTERNS):
                return "js_challenge"
        except Exception:
            pass

        return "none"

    @staticmethod
    async def has_clearance_cookie(page: "Page") -> bool:
        """Check whether cf_clearance cookie is present."""
        try:
            cookies = await page.context.cookies()
            return any(c["name"] == CF_CLEARANCE for c in cookies
                       if c.get("name") == CF_SUCCESS_COOKIE)
        except Exception:
            return False


# ─── 7.1b CloudflareBypass ────────────────────────────────────────────────────

class CloudflareBypass:
    """
    Execute bypass strategies for each Cloudflare challenge type.

    Instantiate with a MouseEngine for human-like interactions.
    """

    JS_CHALLENGE_TIMEOUT = 15.0   # seconds to wait for cf_clearance after JS runs
    TURNSTILE_TIMEOUT = 30.0      # seconds to wait for Turnstile token
    POLL_INTERVAL = 0.5           # seconds between cookie/token polls

    def __init__(self, mouse_engine: Optional["MouseEngine"] = None) -> None:
        if mouse_engine is None and MouseEngine is not None:
            mouse_engine = MouseEngine()
        self.mouse = mouse_engine

    # ── JS Challenge ──────────────────────────────────────────────────────────

    async def bypass_js_challenge(
        self,
        page: "Page",
        timeout: float = JS_CHALLENGE_TIMEOUT,
    ) -> bool:
        """
        Wait for Cloudflare JS challenge to resolve automatically.
        Playwright executes the JS fingerprinting challenge — we just wait
        for cf_clearance cookie to appear.

        Returns True if clearance obtained within timeout.
        """
        logger.info("[CF/Bypass] Waiting for JS challenge to auto-resolve (%.0fs)", timeout)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                cookies = await page.context.cookies()
                if any(c.get("name") == CF_SUCCESS_COOKIE for c in cookies):
                    logger.info("[CF/Bypass] ✅ cf_clearance cookie obtained")
                    return True
            except Exception:
                pass

            # Also check if redirect happened (challenge page gone)
            try:
                is_still_challenge = await CloudflareDetector.is_cloudflare_challenge(page)
                if not is_still_challenge:
                    logger.info("[CF/Bypass] ✅ Challenge page dismissed")
                    return True
            except Exception:
                pass

            await asyncio.sleep(self.POLL_INTERVAL)

        logger.warning("[CF/Bypass] ❌ JS challenge timeout after %.0fs", timeout)
        return False

    # ── Turnstile ────────────────────────────────────────────────────────────

    async def bypass_turnstile(
        self,
        page: "Page",
        timeout: float = TURNSTILE_TIMEOUT,
    ) -> bool:
        """
        Bypass Cloudflare Turnstile challenge.
        1. Locate Turnstile iframe
        2. Click the checkbox with human-like MouseEngine movement
        3. Wait for success token (cf-turnstile-response input)
        """
        logger.info("[CF/Bypass/Turnstile] Starting Turnstile bypass (%.0fs timeout)", timeout)

        # Find Turnstile iframe
        turnstile_frame: Optional["Frame"] = None
        for sel in CF_TURNSTILE_SELECTORS:
            try:
                elem = await page.wait_for_selector(sel, timeout=5000)
                if elem:
                    turnstile_frame = await elem.content_frame()
                    break
            except Exception:
                continue

        if turnstile_frame is None:
            logger.warning("[CF/Bypass/Turnstile] Iframe not found")
            return False

        # Click the checkbox inside iframe
        try:
            checkbox = await turnstile_frame.wait_for_selector(
                "input[type='checkbox'], .cf-turnstile-label, [class*='checkbox']",
                timeout=8000,
            )
            if checkbox is None:
                logger.warning("[CF/Bypass/Turnstile] Checkbox not found in iframe")
                return False

            box = await checkbox.bounding_box()
            if box and self.mouse:
                # Move to checkbox center with human-like bezier path
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                await self.mouse.move_to(page, cx, cy, target_size=box["width"])
                await asyncio.sleep(random.uniform(0.2, 0.5))
                await self.mouse.click(page, cx, cy)
                logger.info("[CF/Bypass/Turnstile] Clicked checkbox at (%.0f, %.0f)", cx, cy)
            else:
                await checkbox.click()
        except Exception as exc:
            logger.warning("[CF/Bypass/Turnstile] Click failed: %s", exc)
            return False

        # Wait for success token
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                # Turnstile injects a hidden input with the response token
                token_elem = await page.query_selector(
                    "input[name='cf-turnstile-response']"
                )
                if token_elem:
                    token_val = await token_elem.get_attribute("value")
                    if token_val and len(token_val) > 10:
                        logger.info(
                            "[CF/Bypass/Turnstile] ✅ Token obtained (len=%d)", len(token_val)
                        )
                        return True
            except Exception:
                pass

            # Also check for cf_clearance cookie
            try:
                cookies = await page.context.cookies()
                if any(c.get("name") == CF_SUCCESS_COOKIE for c in cookies):
                    logger.info("[CF/Bypass/Turnstile] ✅ cf_clearance cookie obtained")
                    return True
            except Exception:
                pass

            await asyncio.sleep(self.POLL_INTERVAL)

        logger.warning("[CF/Bypass/Turnstile] ❌ Timeout after %.0fs", timeout)
        return False

    # ── Header Spoofing ───────────────────────────────────────────────────────

    @staticmethod
    def get_cf_headers(locale: str = "en-US", platform: str = "Win32") -> Dict[str, str]:
        """
        Return Cloudflare-compatible spoofed request headers.
        Proper sec-ch-ua headers prevent early JS bot signals.
        """
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                     "image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": f"{locale},{locale.split('-')[0]};q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": f'"{platform}"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }


# ─── Rate Limit Handler ───────────────────────────────────────────────────────

class CloudflareRateLimitHandler:
    """Handle Cloudflare rate-limit (429 / 1020) responses."""

    @staticmethod
    async def wait_and_retry(
        page: "Page",
        url: str,
        retry_after: float = 30.0,
    ) -> bool:
        """
        Wait for Retry-After period then navigate again.
        Returns True if the retry succeeds.
        """
        # Add jitter to avoid fixed retry patterns
        wait_time = retry_after + random.uniform(5.0, 15.0)
        logger.info(
            "[CF/RateLimit] Rate limited. Waiting %.0fs before retry → %s",
            wait_time, url
        )
        await asyncio.sleep(wait_time)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            is_challenge = await CloudflareDetector.is_cloudflare_challenge(page)
            return not is_challenge
        except Exception as exc:
            logger.warning("[CF/RateLimit] Retry failed: %s", exc)
            return False
