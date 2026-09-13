"""
ironcore/browser/bot_evasion.py — Phase 7.3: BotDetectionEvasion Orchestrator

Unified entry point that:
  1. Detects which bot protection system is active (Cloudflare vs DataDome)
  2. Routes to the correct bypass strategy
  3. Retries up to 3 times with profile rotation between attempts
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── Lazy imports ─────────────────────────────────────────────────────────────

try:
    from playwright.async_api import Page
except ImportError:
    Page = Any  # type: ignore

try:
    from ironcore.browser.cloudflare_bypass import (
        CloudflareDetector,
        CloudflareBypass,
        CloudflareRateLimitHandler,
    )
    _CF_AVAILABLE = True
except ImportError:
    _CF_AVAILABLE = False

try:
    from ironcore.browser.datadome_bypass import (
        DataDomeDetector,
        DataDomeBypass,
    )
    _DD_AVAILABLE = True
except ImportError:
    _DD_AVAILABLE = False

try:
    from ironcore.browser.reddit_bypass import RedditDetector, RedditBypass
    _REDDIT_AVAILABLE = True
except ImportError:
    _REDDIT_AVAILABLE = False

try:
    from ironcore.browser.google_form_bypass import GoogleFormDetector, GoogleFormBypass
    _GFORM_AVAILABLE = True
except ImportError:
    _GFORM_AVAILABLE = False

try:
    from ironcore.browser.mouse_engine import MouseEngine
except ImportError:
    MouseEngine = None  # type: ignore


# ─── Challenge type constants ─────────────────────────────────────────────────

class ChallengeType:
    NONE              = "none"
    CF_JS             = "cloudflare_js"
    CF_TURNSTILE      = "cloudflare_turnstile"
    CF_RATE_LIMIT     = "cloudflare_rate_limit"
    DATADOME_SOFT     = "datadome_soft"
    DATADOME_CAPTCHA  = "datadome_captcha"
    DATADOME_HARD     = "datadome_hard"
    REDDIT_RATE_LIMIT = "reddit_rate_limit"
    REDDIT_SOFT_BLOCK = "reddit_soft_block"
    GFORM_RECAPTCHA_V3         = "gform_recaptcha_v3"
    GFORM_RECAPTCHA_V2         = "gform_recaptcha_v2_checkbox"
    GFORM_RECAPTCHA_V2_IMAGE   = "gform_recaptcha_v2_image"
    UNKNOWN           = "unknown"


class BypassResult:
    """Result of a bypass attempt."""
    __slots__ = ("success", "challenge_type", "attempts", "method_used", "error")

    def __init__(
        self,
        success: bool,
        challenge_type: str = ChallengeType.NONE,
        attempts: int = 1,
        method_used: str = "none",
        error: Optional[str] = None,
    ) -> None:
        self.success = success
        self.challenge_type = challenge_type
        self.attempts = attempts
        self.method_used = method_used
        self.error = error

    def __repr__(self) -> str:
        return (
            f"BypassResult(success={self.success}, type={self.challenge_type!r}, "
            f"attempts={self.attempts}, method={self.method_used!r})"
        )


# ─── BotDetectionEvasion orchestrator ─────────────────────────────────────────

class BotDetectionEvasion:
    """
    Phase 7.3 — Unified bot detection handler.

    Detects the protection system, selects the bypass strategy, and retries
    with exponential backoff + profile rotation if needed.

    Usage:
        evasion = BotDetectionEvasion()
        result = await evasion.handle_challenge(page, url="https://target.com")
        if result.success:
            # page is now past the challenge
            ...
        else:
            # needs different profile or manual intervention
    """

    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 5.0    # seconds base delay between retries
    RETRY_JITTER = 3.0        # ± jitter seconds

    def __init__(
        self,
        mouse_engine: Optional["MouseEngine"] = None,
    ) -> None:
        if mouse_engine is None and MouseEngine is not None:
            mouse_engine = MouseEngine()

        self._cf_bypass = CloudflareBypass(mouse_engine) if _CF_AVAILABLE else None
        self._dd_bypass = DataDomeBypass(mouse_engine) if _DD_AVAILABLE else None
        self._reddit_bypass = RedditBypass(mouse_engine) if _REDDIT_AVAILABLE else None
        self._gform_bypass = GoogleFormBypass(mouse_engine) if _GFORM_AVAILABLE else None

    # ── Public API ────────────────────────────────────────────────────────────

    async def detect(self, page: "Page") -> str:
        """
        Identify which bot protection system is active.
        Returns a ChallengeType constant.
        """
        # Cloudflare check first (more distinctive signatures)
        if _CF_AVAILABLE:
            is_cf = await CloudflareDetector.is_cloudflare_challenge(page)
            if is_cf:
                cf_type = await CloudflareDetector.detect_challenge_type(page)
                if cf_type == "turnstile":
                    return ChallengeType.CF_TURNSTILE
                elif cf_type == "rate_limit":
                    return ChallengeType.CF_RATE_LIMIT
                else:
                    return ChallengeType.CF_JS

        # DataDome check
        if _DD_AVAILABLE:
            is_dd = await DataDomeDetector.is_blocked(page)
            if is_dd:
                dd_type = await DataDomeDetector.detect_block_type(page)
                if dd_type == "captcha":
                    return ChallengeType.DATADOME_CAPTCHA
                elif dd_type == "hard_block":
                    return ChallengeType.DATADOME_HARD
                elif dd_type == "soft_block":
                    return ChallengeType.DATADOME_SOFT

        # Reddit check
        if _REDDIT_AVAILABLE and RedditDetector.is_reddit_url(page.url):
            reddit_type = await RedditDetector.detect_block_type(page)
            if reddit_type == "rate_limit":
                return ChallengeType.REDDIT_RATE_LIMIT
            elif reddit_type in ("soft_block", "captcha"):
                return ChallengeType.REDDIT_SOFT_BLOCK

        # Google Forms check
        if _GFORM_AVAILABLE and await GoogleFormDetector.is_google_form(page):
            gform_type = await GoogleFormDetector.detect_captcha_type(page)
            if gform_type == "recaptcha_v3":
                return ChallengeType.GFORM_RECAPTCHA_V3
            elif gform_type == "recaptcha_v2_checkbox":
                return ChallengeType.GFORM_RECAPTCHA_V2
            elif gform_type == "recaptcha_v2_image":
                return ChallengeType.GFORM_RECAPTCHA_V2_IMAGE

        return ChallengeType.NONE

    async def handle_challenge(
        self,
        page: "Page",
        url: Optional[str] = None,
        on_profile_rotate: Optional[Callable[[], Coroutine]] = None,
    ) -> BypassResult:
        """
        Detect and bypass the active bot challenge.
        Retries up to MAX_RETRIES times with backoff and optional profile rotation.

        Args:
            page: Active Playwright Page.
            url: Target URL to re-navigate to on retry (optional).
            on_profile_rotate: async callback to swap browser profile between retries.

        Returns:
            BypassResult with success status and diagnostics.
        """
        challenge_type = await self.detect(page)

        if challenge_type == ChallengeType.NONE:
            logger.info("[BotEvasion] No challenge detected on %s", page.url)
            return BypassResult(success=True, challenge_type=ChallengeType.NONE)

        logger.info("[BotEvasion] Challenge detected: %s on %s", challenge_type, page.url)

        last_error: Optional[str] = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            logger.info(
                "[BotEvasion] Bypass attempt %d/%d — %s",
                attempt, self.MAX_RETRIES, challenge_type
            )

            success, method = await self._execute_bypass(page, challenge_type, url)

            if success:
                logger.info(
                    "[BotEvasion] ✅ Bypass succeeded (attempt %d, method=%s)",
                    attempt, method
                )
                return BypassResult(
                    success=True,
                    challenge_type=challenge_type,
                    attempts=attempt,
                    method_used=method,
                )

            last_error = f"attempt_{attempt}_failed"

            # Between retries: backoff + optional profile rotation
            if attempt < self.MAX_RETRIES:
                delay = self.RETRY_BASE_DELAY * attempt + random.uniform(
                    -self.RETRY_JITTER, self.RETRY_JITTER
                )
                delay = max(2.0, delay)
                logger.info(
                    "[BotEvasion] Retry in %.1fs (attempt %d/%d)",
                    delay, attempt, self.MAX_RETRIES
                )
                await asyncio.sleep(delay)

                if on_profile_rotate is not None:
                    try:
                        await on_profile_rotate()
                        logger.info("[BotEvasion] Profile rotated")
                    except Exception as exc:
                        logger.warning("[BotEvasion] Profile rotation failed: %s", exc)

                # Re-navigate if URL provided
                if url:
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                        # Re-detect challenge type after reload
                        challenge_type = await self.detect(page)
                        if challenge_type == ChallengeType.NONE:
                            return BypassResult(
                                success=True,
                                challenge_type=ChallengeType.NONE,
                                attempts=attempt,
                                method_used="retry_cleared",
                            )
                    except Exception as exc:
                        logger.warning("[BotEvasion] Re-navigation failed: %s", exc)

        logger.error(
            "[BotEvasion] ❌ All %d bypass attempts failed for %s",
            self.MAX_RETRIES, challenge_type
        )
        return BypassResult(
            success=False,
            challenge_type=challenge_type,
            attempts=self.MAX_RETRIES,
            method_used="exhausted",
            error=last_error,
        )

    async def pre_request_prime(
        self,
        page: "Page",
        locale: str = "en-US",
        platform: str = "Win32",
        user_agent: str = "",
    ) -> None:
        """
        Pre-request setup: install DataDome header interceptor.
        Call before page.goto() to ensure all requests carry correct headers.
        """
        if self._dd_bypass and _DD_AVAILABLE:
            await self._dd_bypass.install_header_interceptor(
                page, locale=locale, platform=platform, user_agent=user_agent
            )
            logger.debug("[BotEvasion] Header interceptor installed")

    async def post_navigation_prime(
        self,
        page: "Page",
        min_dwell: float = 5.0,
    ) -> None:
        """
        Post-navigation behavioral priming.
        Call after page.goto() to build trust with DataDome before interacting.
        """
        if self._dd_bypass and _DD_AVAILABLE:
            await self._dd_bypass.prime_behavioral_signals(page, min_duration=min_dwell)

    # ── Internal dispatch ─────────────────────────────────────────────────────

    async def _execute_bypass(
        self,
        page: "Page",
        challenge_type: str,
        url: Optional[str],
    ) -> tuple[bool, str]:
        """
        Dispatch to the correct bypass handler.
        Returns (success: bool, method_name: str).
        """
        try:
            if challenge_type == ChallengeType.CF_JS:
                if self._cf_bypass and _CF_AVAILABLE:
                    ok = await self._cf_bypass.bypass_js_challenge(page)
                    return ok, "cf_js_wait"

            elif challenge_type == ChallengeType.CF_TURNSTILE:
                if self._cf_bypass and _CF_AVAILABLE:
                    ok = await self._cf_bypass.bypass_turnstile(page)
                    return ok, "cf_turnstile_click"

            elif challenge_type == ChallengeType.CF_RATE_LIMIT:
                if url and _CF_AVAILABLE:
                    ok = await CloudflareRateLimitHandler.wait_and_retry(page, url)
                    return ok, "cf_rate_limit_wait"
                return False, "cf_rate_limit_no_url"

            elif challenge_type in (
                ChallengeType.DATADOME_SOFT,
                ChallengeType.DATADOME_CAPTCHA,
            ):
                if self._dd_bypass and _DD_AVAILABLE:
                    # Prime behavioral signals to satisfy DataDome
                    await self._dd_bypass.prime_behavioral_signals(
                        page, min_duration=15.0
                    )
                    # Re-check if block is cleared
                    still_blocked = await DataDomeDetector.is_blocked(page)
                    return (not still_blocked), "dd_behavioral_prime"

            elif challenge_type == ChallengeType.DATADOME_HARD:
                logger.error(
                    "[BotEvasion] Hard block — needs new IP/proxy, not software-bypassable"
                )
                return False, "dd_hard_block"

            elif challenge_type == ChallengeType.REDDIT_RATE_LIMIT:
                if self._reddit_bypass and url and _REDDIT_AVAILABLE:
                    ok = await self._reddit_bypass.handle_rate_limit(page, url)
                    return ok, "reddit_rate_limit_wait"
                return False, "reddit_rate_limit_no_handler"

            elif challenge_type == ChallengeType.REDDIT_SOFT_BLOCK:
                if self._reddit_bypass and url and _REDDIT_AVAILABLE:
                    ok = await self._reddit_bypass.recover_soft_block(page, url)
                    return ok, "reddit_old_reddit_fallback"
                return False, "reddit_soft_block_no_handler"

            elif challenge_type == ChallengeType.GFORM_RECAPTCHA_V3:
                if self._gform_bypass and _GFORM_AVAILABLE:
                    await self._gform_bypass.prime_recaptcha_v3(page, dwell_seconds=20.0)
                    still_blocked = await GoogleFormDetector.is_submission_blocked(page)
                    return (not still_blocked), "gform_v3_behavioral_prime"
                return False, "gform_v3_no_handler"

            elif challenge_type == ChallengeType.GFORM_RECAPTCHA_V2:
                if self._gform_bypass and _GFORM_AVAILABLE:
                    ok = await self._gform_bypass.solve_recaptcha_v2_checkbox(page)
                    return ok, "gform_v2_checkbox_click"
                return False, "gform_v2_no_handler"

            elif challenge_type == ChallengeType.GFORM_RECAPTCHA_V2_IMAGE:
                # Image challenge requires VLMBridge — escalate
                logger.warning(
                    "[BotEvasion] reCAPTCHA v2 image challenge — escalate to VLMBridge"
                )
                return False, "gform_v2_image_needs_vlm"

        except Exception as exc:
            logger.error("[BotEvasion] Bypass execution error: %s", exc)
            return False, f"exception:{type(exc).__name__}"

        logger.warning("[BotEvasion] No handler for challenge_type=%s", challenge_type)
        return False, "no_handler"
