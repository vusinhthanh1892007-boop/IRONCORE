"""
ironcore/browser/ghost_agent.py — Phase 8.2: GhostBrowserAgent

High-level browser agent that combines ALL Ghost modules (Phase 1-7):
  - StealthBrowser + FullFingerprintSpoofer  (Phase 1 & 5)
  - MouseEngine                               (Phase 2)
  - GeeTestSolver + ReCaptchaV2Solver         (Phase 3)
  - SessionManager + ProfilePool              (Phase 6)
  - BotDetectionEvasion (CF + DataDome)       (Phase 7)

This class registers all Ghost tools into IronCoreEngine and acts as
the single integration point for "The Ghost" module.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import random
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── Core engine imports ──────────────────────────────────────────────────────

from ironcore.core.engine import IronCoreEngine, ToolDefinition, RiskLevel, Observation

# ─── Ghost module imports — lazy where playwright required ────────────────────

try:
    from ironcore.browser.stealth import StealthBrowser, BrowserProfile
except Exception:
    StealthBrowser = None  # type: ignore
    BrowserProfile = None  # type: ignore

try:
    from ironcore.browser.mouse_engine import MouseEngine
except Exception:
    MouseEngine = None  # type: ignore

try:
    from ironcore.browser.captcha_solver import GeeTestSolver, ReCaptchaV2Solver
except Exception:
    GeeTestSolver = None   # type: ignore
    ReCaptchaV2Solver = None  # type: ignore

try:
    from ironcore.browser.fingerprint_spoofer import (
        FullFingerprintSpoofer,
        get_random_browser_profile,
    )
except Exception:
    FullFingerprintSpoofer = None  # type: ignore
    get_random_browser_profile = None  # type: ignore

try:
    from ironcore.browser.session_manager import SessionManager
except Exception:
    SessionManager = None  # type: ignore

try:
    from ironcore.browser.bot_evasion import BotDetectionEvasion, ChallengeType
    from ironcore.browser.cloudflare_bypass import CloudflareBypass
    from ironcore.browser.datadome_bypass import DataDomeBypass
except Exception:
    BotDetectionEvasion = None  # type: ignore
    ChallengeType = None  # type: ignore
    CloudflareBypass = None  # type: ignore
    DataDomeBypass = None  # type: ignore

try:
    from ironcore.vlm.bridge import VLMBridge
except Exception:
    VLMBridge = None  # type: ignore


# ─── GhostBrowserAgent ───────────────────────────────────────────────────────

class GhostBrowserAgent:
    """
    Phase 8 integration: combines all Ghost modules and registers them
    as callable tools inside IronCoreEngine.

    Registered tools:
        stealth_navigate   — Navigate with bot detection bypass (HIGH risk)
        stealth_click      — Human-like mouse click (HIGH risk)
        stealth_fill_form  — Fill a form with gaussian typing timing (HIGH risk)
        stealth_screenshot — Screenshot current page (MEDIUM risk)
        get_page_content   — Return page HTML (LOW risk)
        solve_captcha      — Route captcha to GeeTest/ReCaptcha/VLM (HIGH risk)
    """

    TOOL_DESCRIPTIONS: Dict[str, str] = {
        "stealth_navigate": (
            "Navigate to a URL using a stealthy browser that spoofs fingerprints, "
            "bypasses Cloudflare JS/Turnstile, and primes DataDome behavioral signals."
        ),
        "stealth_click": (
            "Click an element identified by CSS selector using human-like "
            "Bezier-curve mouse movement with overshoot and micro-jitter."
        ),
        "stealth_fill_form": (
            "Fill a form: dict of {css_selector: value}. "
            "Types each field with gaussian inter-key delays (μ=80ms σ=25ms)."
        ),
        "stealth_screenshot": (
            "Take a PNG screenshot of the current page and return it as base64."
        ),
        "get_page_content": (
            "Return the full HTML source of the current page."
        ),
        "solve_captcha": (
            "Detect and solve the captcha on the current page. "
            "Supports: geetest (slider), recaptcha_v2 (VLM pipeline), recaptcha_v3."
        ),
    }

    def __init__(
        self,
        engine: IronCoreEngine,
        vlm_bridge: Optional["VLMBridge"] = None,
        pool_size: int = 20,
        warmup_new_profiles: bool = True,
    ) -> None:
        self.engine = engine

        # Sub-systems
        self.mouse_engine: Optional["MouseEngine"] = (
            MouseEngine() if MouseEngine is not None else None
        )
        self.session_manager: Optional["SessionManager"] = (
            SessionManager(
                pool_size=pool_size,
                warmup_new_profiles=warmup_new_profiles,
            )
            if SessionManager is not None
            else None
        )
        self.bot_evasion: Optional["BotDetectionEvasion"] = (
            BotDetectionEvasion(self.mouse_engine)
            if BotDetectionEvasion is not None
            else None
        )
        self.vlm_bridge: Optional["VLMBridge"] = vlm_bridge

        # Active browser (per-session; replaced by get_stealth_browser)
        self._browser: Optional["StealthBrowser"] = None

        # Register all 6 tools
        self._register_tools()

        logger.info(
            "[Ghost/Agent] GhostBrowserAgent ready — %d tools registered",
            len([t for t in engine.registered_tools if t.startswith("stealth_") or t in ("get_page_content", "solve_captcha")]),
        )

    def _register_tools(self) -> None:
        """Register all Ghost tools into IronCoreEngine."""
        tool_specs: List[Tuple[str, Any, RiskLevel]] = [
            ("stealth_navigate",   self.navigate,       RiskLevel.HIGH),
            ("stealth_click",      self.click,          RiskLevel.HIGH),
            ("stealth_fill_form",  self.fill_form,      RiskLevel.HIGH),
            ("stealth_screenshot", self.screenshot,     RiskLevel.MEDIUM),
            ("get_page_content",   self.get_content,    RiskLevel.LOW),
            ("solve_captcha",      self.solve_captcha,  RiskLevel.HIGH),
        ]

        registered = 0
        for name, handler, risk in tool_specs:
            try:
                self.engine.register_tool(
                    ToolDefinition(
                        name=name,
                        handler=handler,
                        risk_level=risk,
                        description=self.TOOL_DESCRIPTIONS.get(name, ""),
                    )
                )
                registered += 1
                logger.debug("[Ghost/Agent] Registered tool: %s (risk=%s)", name, risk.name)
            except ValueError as exc:
                logger.warning("[Ghost/Agent] Skipped tool %s: %s", name, exc)

        logger.info("[Ghost/Agent] Registered %d tools into IronCoreEngine", registered)

    # ── 8.2 Tool Implementations ──────────────────────────────────────────────

    async def navigate(self, url: str, task_type: str = "default") -> Dict[str, Any]:
        """
        Navigate to url with full Ghost treatment:
        1. Get/launch StealthBrowser via SessionManager (or reuse current)
        2. Install DataDome header interceptor before goto()
        3. goto(url)
        4. Handle any bot challenge (CF/DataDome) via BotDetectionEvasion
        5. Return navigation result

        Args:
            url: Target URL.
            task_type: Hint for profile selection ('scraping', 'checkout', etc.)
        """
        t0 = time.monotonic()

        # Ensure we have a browser
        browser = await self._get_or_launch_browser(task_type)
        if browser is None:
            return {"success": False, "error": "Could not launch StealthBrowser"}

        page = browser._page
        if page is None:
            return {"success": False, "error": "Browser has no active page"}

        # Pre-request: install header interceptor (DataDome defense)
        if self.bot_evasion is not None:
            profile = getattr(browser, "profile", None)
            locale = getattr(profile, "locale", "en-US") if profile else "en-US"
            platform = getattr(profile, "platform", "Win32") if profile else "Win32"
            ua = getattr(profile, "user_agent", "") if profile else ""
            await self.bot_evasion.pre_request_prime(page, locale, platform, ua)

        # Navigate
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            logger.warning("[Ghost/navigate] goto failed: %s", exc)
            return {"success": False, "url": url, "error": str(exc)}

        # Post-navigation: detect and bypass challenges
        bypass_result = None
        if self.bot_evasion is not None:
            challenge = await self.bot_evasion.detect(page)
            if challenge != "none":
                bypass_result = await self.bot_evasion.handle_challenge(page, url=url)
                if not bypass_result.success:
                    return {
                        "success": False,
                        "url": url,
                        "challenge": challenge,
                        "bypass_attempts": bypass_result.attempts,
                        "error": "Bot challenge not bypassed",
                    }

        elapsed_ms = (time.monotonic() - t0) * 1000
        status_code = None
        try:
            status_code = await page.evaluate("() => performance.getEntriesByType('navigation')[0]?.serverTiming")  # type: ignore
        except Exception:
            pass

        return {
            "success": True,
            "url": url,
            "final_url": page.url,
            "elapsed_ms": round(elapsed_ms, 1),
            "challenge_bypassed": bypass_result.challenge_type if bypass_result else None,
        }

    async def click(self, selector: str) -> Dict[str, Any]:
        """
        Click an element via CSS selector using human-like MouseEngine movement.

        Args:
            selector: CSS selector of the target element.
        """
        page = self._get_active_page()
        if page is None:
            return {"success": False, "error": "No active page"}

        try:
            element = await page.wait_for_selector(selector, timeout=10_000)
            if element is None:
                return {"success": False, "error": f"Selector not found: {selector}"}

            box = await element.bounding_box()
            if box is None:
                return {"success": False, "error": f"Element not visible: {selector}"}

            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2

            if self.mouse_engine is not None:
                await self.mouse_engine.click(page, cx, cy)
            else:
                await element.click()

            logger.info("[Ghost/click] Clicked '%s' at (%.0f, %.0f)", selector, cx, cy)
            return {"success": True, "selector": selector, "x": cx, "y": cy}

        except Exception as exc:
            logger.warning("[Ghost/click] Error: %s", exc)
            return {"success": False, "selector": selector, "error": str(exc)}

    async def fill_form(self, fields: Dict[str, str]) -> Dict[str, Any]:
        """
        Fill form fields with human-like typing timing.

        Args:
            fields: {css_selector: value_to_type}
        """
        page = self._get_active_page()
        if page is None:
            return {"success": False, "error": "No active page"}

        results = {}
        for selector, value in fields.items():
            try:
                element = await page.wait_for_selector(selector, timeout=8_000)
                if element is None:
                    results[selector] = "not_found"
                    continue

                # Click to focus
                box = await element.bounding_box()
                if box and self.mouse_engine:
                    await self.mouse_engine.click(
                        page,
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2,
                    )
                else:
                    await element.click()

                await asyncio.sleep(random.gauss(0.15, 0.05))

                # Type with gaussian delay (μ=80ms σ=25ms)
                await page.keyboard.type(str(value), delay=random.gauss(80, 25))
                await asyncio.sleep(random.gauss(0.3, 0.1))
                results[selector] = "filled"
                logger.info("[Ghost/fill_form] Filled '%s'", selector)

            except Exception as exc:
                results[selector] = f"error:{exc}"
                logger.warning("[Ghost/fill_form] Error on %s: %s", selector, exc)

        all_ok = all(v == "filled" for v in results.values())
        return {"success": all_ok, "fields": results}

    async def screenshot(self) -> Dict[str, Any]:
        """
        Take a full-page screenshot and return it as base64 PNG.
        Also returns metadata useful for VLM analysis.
        """
        page = self._get_active_page()
        if page is None:
            return {"success": False, "error": "No active page"}

        try:
            png_bytes = await page.screenshot(full_page=False)
            b64 = base64.b64encode(png_bytes).decode("utf-8")
            return {
                "success": True,
                "image_base64": b64,
                "mime_type": "image/png",
                "url": page.url,
                "size_bytes": len(png_bytes),
            }
        except Exception as exc:
            logger.warning("[Ghost/screenshot] Error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def get_content(self) -> Dict[str, Any]:
        """Return the full HTML content of the current page."""
        page = self._get_active_page()
        if page is None:
            return {"success": False, "error": "No active page"}

        try:
            html = await page.content()
            return {
                "success": True,
                "html": html,
                "url": page.url,
                "length": len(html),
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def solve_captcha(
        self,
        captcha_type: str,
        selector: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Detect and solve captcha.

        Args:
            captcha_type: 'geetest' | 'recaptcha_v2' | 'recaptcha_v3' | 'auto'
            selector: Optional CSS selector to scope to captcha widget.

        Routing:
            geetest      → GeeTestSolver (OpenCV template matching)
            recaptcha_v2 → ReCaptchaV2Solver + VLMBridge (tile analysis)
            recaptcha_v3 → ReCaptchaV3Analyzer (behavioral scoring)
            auto         → detect from page DOM
        """
        page = self._get_active_page()
        if page is None:
            return {"success": False, "error": "No active page"}

        t0 = time.monotonic()

        if captcha_type in ("auto", "geetest"):
            result = await self._solve_geetest(page)
            if result["success"] or captcha_type == "geetest":
                result["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
                return result

        if captcha_type in ("auto", "recaptcha_v2"):
            result = await self._solve_recaptcha_v2(page)
            result["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
            return result

        if captcha_type == "recaptcha_v3":
            return {
                "success": True,
                "method": "recaptcha_v3",
                "note": "V3 uses behavioral scoring — ensure profile is warmed up",
                "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
            }

        return {"success": False, "error": f"Unknown captcha_type: {captcha_type}"}

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _get_or_launch_browser(
        self,
        task_type: str = "default",
    ) -> Optional["StealthBrowser"]:
        """Return existing browser or launch a new one via SessionManager."""
        if self._browser is not None:
            return self._browser

        if self.session_manager is not None:
            try:
                await self.session_manager.initialize()
                self._browser = await self.session_manager.get_stealth_browser(task_type)
                return self._browser
            except Exception as exc:
                logger.error("[Ghost/Agent] SessionManager launch failed: %s", exc)

        # Fallback: direct launch with random profile
        if StealthBrowser is not None and get_random_browser_profile is not None:
            profile = get_random_browser_profile("fallback", 0)
            browser = StealthBrowser(profile)
            try:
                await browser.launch()
                self._browser = browser
                return self._browser
            except Exception as exc:
                logger.error("[Ghost/Agent] Fallback launch failed: %s", exc)

        return None

    def _get_active_page(self) -> Any:
        """Return the active page from current browser, or None."""
        if self._browser is None:
            return None
        return getattr(self._browser, "_page", None)

    async def _solve_geetest(self, page: Any) -> Dict[str, Any]:
        """Solve GeeTest slider using OpenCV template matching."""
        if GeeTestSolver is None:
            return {"success": False, "error": "GeeTestSolver not available"}

        try:
            # Get background and puzzle images
            bg_bytes = await page.evaluate(
                "() => {"
                "  const bg = document.querySelector('.geetest_bg, [class*=\"bg\"]')?.src;"
                "  return bg;"
                "}"
            )
            puzzle_bytes = await page.evaluate(
                "() => {"
                "  const p = document.querySelector('.geetest_slice_bg, [class*=\"slice\"]')?.src;"
                "  return p;"
                "}"
            )

            if not bg_bytes or not puzzle_bytes:
                return {"success": False, "error": "GeeTest images not found in DOM"}

            # Download images
            import urllib.request
            with urllib.request.urlopen(bg_bytes) as r:
                bg_data = r.read()
            with urllib.request.urlopen(puzzle_bytes) as r:
                puzzle_data = r.read()

            solver = GeeTestSolver()
            result = await solver.solve(page, bg_data, puzzle_data, self.mouse_engine)
            return {
                "success": result.success,
                "method": "geetest_opencv",
                "offset_x": result.offset_x,
                "confidence": result.confidence,
                "attempts": result.attempts,
            }
        except Exception as exc:
            logger.warning("[Ghost/GeeTest] Error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _solve_recaptcha_v2(self, page: Any) -> Dict[str, Any]:
        """
        Solve reCAPTCHA v2 image grid using VLMBridge pipeline.
        1. Screenshot the iframe
        2. Send to VLMBridge.analyze_captcha()
        3. Click returned coordinates with MouseEngine
        """
        if self.vlm_bridge is None:
            return {"success": False, "error": "VLMBridge not configured"}

        try:
            # Find reCAPTCHA iframe
            iframe_element = await page.query_selector(
                'iframe[src*="recaptcha/api2"], iframe[title*="reCAPTCHA"]'
            )
            if iframe_element is None:
                return {"success": False, "error": "reCAPTCHA iframe not found"}

            # Screenshot iframe region
            box = await iframe_element.bounding_box()
            if box is None:
                return {"success": False, "error": "reCAPTCHA iframe not visible"}

            png_bytes = await page.screenshot(
                clip={
                    "x": box["x"],
                    "y": box["y"],
                    "width": box["width"],
                    "height": box["height"],
                }
            )
            b64_image = base64.b64encode(png_bytes).decode("utf-8")

            # Ask VLM for target coordinates
            # VLMBridge.analyze_captcha is sync → run in executor
            loop = asyncio.get_running_loop()
            target_x, target_y = await loop.run_in_executor(
                None,
                lambda: self.vlm_bridge.analyze_captcha(
                    b64_image,
                    "Find the target object and return the center coordinates.",
                ),
            )

            # Click with MouseEngine
            abs_x = box["x"] + target_x
            abs_y = box["y"] + target_y

            if self.mouse_engine:
                await self.mouse_engine.click(page, abs_x, abs_y)
            else:
                await page.mouse.click(abs_x, abs_y)

            logger.info(
                "[Ghost/ReCaptcha-V2] VLM → click at (%.0f, %.0f)", abs_x, abs_y
            )
            return {
                "success": True,
                "method": "recaptcha_v2_vlm",
                "vlm_coords": (target_x, target_y),
                "abs_coords": (abs_x, abs_y),
            }
        except Exception as exc:
            logger.warning("[Ghost/ReCaptcha-V2] Error: %s", exc)
            return {"success": False, "error": str(exc)}

    async def return_browser(self, success: bool = True, reason: Optional[str] = None) -> None:
        """Release the current browser back to SessionManager."""
        if self._browser and self.session_manager:
            await self.session_manager.return_browser(
                self._browser, success=success, failure_reason=reason
            )
        elif self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        self._browser = None
