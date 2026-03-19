"""
ironcore/browser/google_form_bypass.py — Google Form & reCAPTCHA v3 Bypass

Google Forms bot-protection layers (2026):
  - reCAPTCHA v3: invisible, score-based (0.0=bot, 1.0=human). Threshold ~0.5.
    Actions are tied to each form: "submit", "login", "contact", etc.
  - reCAPTCHA v2 checkbox: "I'm not a robot" visible challenge (fallback)
  - reCAPTCHA v2 image: audio/image puzzle (deep fallback for low v3 score)
  - Honeypot fields: hidden inputs that bots typically fill
  - Behavioral scoring: typing speed, mouse path, form fill timing
  - Google account requirement: some forms reject unauthenticated submissions

Strategy:
  1. GoogleFormDetector — identify which protection layer is active
  2. GoogleFormBypass:
     a. Inject human-like form fill timing (random keystroke delays)
     b. Mouse movement to each field before focus
     c. Honor reCAPTCHA v3 score via human-behavior priming before token request
     d. reCAPTCHA v2 checkbox: click with MouseEngine + bezier path
     e. Check for and skip honeypot fields
     f. Submit with natural delay after last field
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── Lazy imports ─────────────────────────────────────────────────────────────

try:
    from playwright.async_api import Page, Frame, ElementHandle
except ImportError:
    Page = Any  # type: ignore
    Frame = Any  # type: ignore
    ElementHandle = Any  # type: ignore

try:
    from ironcore.browser.mouse_engine import MouseEngine
except ImportError:
    MouseEngine = None  # type: ignore

# ─── Selectors & signatures ───────────────────────────────────────────────────

# reCAPTCHA v3 — invisible, score-based
RECAPTCHA_V3_BADGE = ".grecaptcha-badge"
RECAPTCHA_V3_SCRIPT_PATTERN = r"grecaptcha\.execute\("

# reCAPTCHA v2 checkbox widget
RECAPTCHA_V2_SELECTORS = [
    "iframe[src*='recaptcha/api2/anchor']",
    "iframe[src*='recaptcha/enterprise/anchor']",
    "div.g-recaptcha",
    "[data-callback]",
]
RECAPTCHA_V2_CHECKBOX = "#recaptcha-anchor"
RECAPTCHA_V2_SUCCESS = "span.recaptcha-checkbox-checked"

# Google Forms structural selectors
GOOGLE_FORM_ROOT = "form[action*='docs.google.com/forms']"
GOOGLE_FORM_SUBMIT = [
    "div[role='button'][jsname]",           # new Forms UI submit
    "input[type='submit']",
    "button[type='submit']",
    "*[aria-label*='Submit']",
    "*[aria-label*='submit']",
]
GOOGLE_FORM_TEXT_INPUTS = [
    "input[type='text']:not([aria-hidden='true'])",
    "textarea:not([aria-hidden='true'])",
    "input[type='email']",
    "input[type='number']",
]
HONEYPOT_CLUES = [
    "display:none",
    "visibility:hidden",
    "opacity:0",
    "position:absolute.*left:-",
    "tab-index.*-1",
]

# Typing cadence constants (ms between keystrokes)
_TYPING_DELAY_MIN_MS = 60
_TYPING_DELAY_MAX_MS = 180
_TYPO_RATE = 0.04  # 4% chance of a typo + backspace per character


# ─── GoogleFormDetector ──────────────────────────────────────────────────────

class GoogleFormDetector:
    """
    Detect which bot-protection layer is active on a Google Form page.
    """

    @staticmethod
    async def detect_captcha_type(page: "Page") -> str:
        """
        Returns: 'recaptcha_v3' | 'recaptcha_v2_checkbox' | 'recaptcha_v2_image' | 'none'
        """
        try:
            content = await page.content()
        except Exception:
            return "none"

        # reCAPTCHA v2 image challenge (rendered inside frame)
        try:
            frames = page.frames
            for frame in frames:
                furl = frame.url
                if "recaptcha" in furl and "bframe" in furl:
                    logger.debug("[GForm/Detector] reCAPTCHA v2 image bframe found")
                    return "recaptcha_v2_image"
        except Exception:
            pass

        # reCAPTCHA v2 checkbox iframe
        for sel in RECAPTCHA_V2_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el:
                    logger.debug("[GForm/Detector] reCAPTCHA v2 checkbox via %s", sel)
                    return "recaptcha_v2_checkbox"
            except Exception:
                pass

        # reCAPTCHA v3 badge or script
        try:
            badge = await page.query_selector(RECAPTCHA_V3_BADGE)
            if badge:
                return "recaptcha_v3"
        except Exception:
            pass
        if re.search(RECAPTCHA_V3_SCRIPT_PATTERN, content):
            return "recaptcha_v3"

        return "none"

    @staticmethod
    async def is_submission_blocked(page: "Page") -> bool:
        """
        Return True if the form submission was rejected (error message shown).
        """
        try:
            content = (await page.content()).lower()
            block_signals = [
                "please verify you're not a robot",
                "security check",
                "captcha",
                "unusual traffic",
                "your response could not be submitted",
            ]
            return any(s in content for s in block_signals)
        except Exception:
            return False

    @staticmethod
    async def is_google_form(page: "Page") -> bool:
        """Return True if the page is a Google Form."""
        try:
            url = page.url
            return "docs.google.com/forms" in url
        except Exception:
            return False


# ─── GoogleFormBypass ────────────────────────────────────────────────────────

class GoogleFormBypass:
    """
    Bypass Google Form bot detection via behavioral mimicry.

    Two main concerns:
      1. reCAPTCHA v3 score — raised by human-like timing before and during fill
      2. Google's own submission throttle — raised by realistic form interaction
    """

    # Minimum dwell before interacting — lets v3 observe "legitimate" session
    MIN_PRE_FILL_DWELL = 3.0
    MAX_PRE_FILL_DWELL = 8.0

    # Delay between filling fields (seconds)
    INTER_FIELD_DELAY_MIN = 0.8
    INTER_FIELD_DELAY_MAX = 2.5

    # Delay between last field and submit button click (seconds)
    PRE_SUBMIT_DELAY_MIN = 1.5
    PRE_SUBMIT_DELAY_MAX = 4.0

    def __init__(self, mouse_engine: Optional["MouseEngine"] = None) -> None:
        self._mouse = mouse_engine

    # ── High-level: fill & submit ─────────────────────────────────────────────

    async def fill_and_submit(
        self,
        page: "Page",
        field_values: Dict[str, str],
        submit_timeout_ms: int = 10_000,
    ) -> bool:
        """
        Fill a Google Form with human-like behavior and submit.

        Args:
            page: Active Playwright Page on a docs.google.com/forms URL.
            field_values: Mapping of CSS selector → value to type.
                          e.g. {"input[aria-label='Name']": "Jane Doe"}
            submit_timeout_ms: Timeout waiting for confirmation after submit.

        Returns:
            True if the form was submitted successfully (no block detected).
        """
        # Phase 1: Pre-fill dwell — let reCAPTCHA v3 observe idle human session
        await self._pre_fill_prime(page)

        # Phase 2: Fill each field
        for selector, value in field_values.items():
            success = await self._fill_field(page, selector, value)
            if not success:
                logger.warning("[GForm/Bypass] Could not fill field: %s", selector)
            await asyncio.sleep(
                random.uniform(self.INTER_FIELD_DELAY_MIN, self.INTER_FIELD_DELAY_MAX)
            )

        # Phase 3: Pre-submit human pause
        await asyncio.sleep(
            random.uniform(self.PRE_SUBMIT_DELAY_MIN, self.PRE_SUBMIT_DELAY_MAX)
        )

        # Phase 4: Click submit
        submitted = await self._click_submit(page, submit_timeout_ms)
        if not submitted:
            return False

        # Phase 5: Check for block
        await asyncio.sleep(2.0)
        blocked = await GoogleFormDetector.is_submission_blocked(page)
        if blocked:
            logger.warning("[GForm/Bypass] Submission blocked — reCAPTCHA score too low")
            return False

        logger.info("[GForm/Bypass] ✅ Form submitted successfully")
        return True

    # ── reCAPTCHA v3: score priming ───────────────────────────────────────────

    async def prime_recaptcha_v3(self, page: "Page", dwell_seconds: float = 15.0) -> None:
        """
        Raise the reCAPTCHA v3 trust score by simulating human behavior
        before the form token is requested.

        Activities performed:
          - Natural scrolling up and down
          - Random mouse movements across the viewport
          - Occasional hover over form elements
          - Realistic dwell without rapid actions
        """
        logger.info("[GForm/Bypass] Priming reCAPTCHA v3 score (%.0fs)", dwell_seconds)
        deadline = time.time() + dwell_seconds

        while time.time() < deadline:
            action = random.choice(["scroll", "mouse_move", "hover", "idle"])
            remaining = deadline - time.time()
            if remaining <= 0:
                break

            try:
                if action == "scroll":
                    dy = random.choice([-1, 1]) * random.randint(100, 400)
                    await page.evaluate(f"window.scrollBy({{top: {dy}, behavior: 'smooth'}})")
                    await asyncio.sleep(random.uniform(0.5, 1.5))

                elif action == "mouse_move":
                    vp = page.viewport_size or {"width": 1280, "height": 720}
                    x = random.randint(50, vp["width"] - 50)
                    y = random.randint(50, vp["height"] - 50)
                    await page.mouse.move(x, y)
                    await asyncio.sleep(random.uniform(0.2, 0.8))

                elif action == "hover":
                    # Hover over a random text input (non-disruptive)
                    inputs = await page.query_selector_all("input[type='text'], textarea")
                    if inputs:
                        target = random.choice(inputs)
                        await target.hover()
                        await asyncio.sleep(random.uniform(0.5, 1.2))

                else:  # idle
                    await asyncio.sleep(random.uniform(1.0, 2.5))

            except Exception:
                await asyncio.sleep(0.5)

    # ── reCAPTCHA v2 checkbox ─────────────────────────────────────────────────

    async def solve_recaptcha_v2_checkbox(self, page: "Page") -> bool:
        """
        Click the reCAPTCHA v2 "I'm not a robot" checkbox.

        Most automated sessions pass the checkbox if:
          - Mouse movement to checkbox is non-linear (bezier path)
          - The page shows sufficient prior human activity
          - Fingerprint is clean (handled by FingerprintSpoofer + MouseEngine)

        Returns True if checkbox is checked after click.
        If v2 image challenge spawns (score bad), returns False —
        caller should escalate to VLMBridge captcha solving.
        """
        # Find the reCAPTCHA anchor iframe
        anchor_frame: Optional["Frame"] = None
        try:
            for frame in page.frames:
                if "recaptcha" in frame.url and "anchor" in frame.url:
                    anchor_frame = frame
                    break
        except Exception:
            pass

        if anchor_frame is None:
            logger.warning("[GForm/Bypass] reCAPTCHA v2 anchor frame not found")
            return False

        # Locate checkbox inside iframe
        try:
            checkbox = await anchor_frame.wait_for_selector(
                RECAPTCHA_V2_CHECKBOX, timeout=5_000
            )
            if checkbox is None:
                return False

            # Use MouseEngine bezier click if available, else direct click
            if self._mouse is not None:
                box = await checkbox.bounding_box()
                if box:
                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] / 2
                    await self._mouse.click(page, cx, cy)
                else:
                    await checkbox.click()
            else:
                await checkbox.click()

            # Wait for check or image challenge
            await asyncio.sleep(2.5)

            # Check if solved (checkbox checked state)
            checked = await anchor_frame.query_selector(RECAPTCHA_V2_SUCCESS)
            if checked:
                logger.info("[GForm/Bypass] ✅ reCAPTCHA v2 checkbox solved")
                return True

            # Image challenge spawned — VLM needed
            for frame in page.frames:
                if "recaptcha" in frame.url and "bframe" in frame.url:
                    logger.warning(
                        "[GForm/Bypass] reCAPTCHA v2 image challenge appeared — "
                        "escalate to VLMBridge"
                    )
                    return False

        except Exception as exc:
            logger.error("[GForm/Bypass] v2 checkbox click error: %s", exc)

        return False

    # ── Field fill ────────────────────────────────────────────────────────────

    async def _fill_field(
        self,
        page: "Page",
        selector: str,
        value: str,
    ) -> bool:
        """
        Fill a single form field with human-like typing.
        - Moves mouse to field before focus
        - Types with realistic random delays per character
        - Occasionally makes a typo and corrects it
        """
        try:
            element = await page.wait_for_selector(selector, timeout=5_000)
            if element is None:
                return False

            # Check if this is a honeypot field
            if await self._is_honeypot(element):
                logger.debug("[GForm/Bypass] Skipping honeypot field: %s", selector)
                return True

            # Mouse move to field
            box = await element.bounding_box()
            if box and self._mouse is not None:
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                await self._mouse.move_to(page, cx, cy)
            elif box:
                await page.mouse.move(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2,
                )

            await element.click()
            await asyncio.sleep(random.uniform(0.2, 0.6))

            # Type character by character with realistic cadence
            await self._human_type(page, element, value)
            return True

        except Exception as exc:
            logger.error("[GForm/Bypass] Field fill error (%s): %s", selector, exc)
            return False

    async def _human_type(
        self,
        page: "Page",
        element: "ElementHandle",
        text: str,
    ) -> None:
        """
        Type `text` into `element` with:
        - Per-character random delay
        - Occasional typo + backspace correction
        - Burst typing then pause (simulates natural rhythm)
        """
        i = 0
        while i < len(text):
            char = text[i]

            # Occasional typo
            if random.random() < _TYPO_RATE and char.isalpha():
                typo_char = chr(ord(char) + random.choice([-1, 1]))
                await element.type(typo_char, delay=0)
                await asyncio.sleep(random.uniform(0.1, 0.3))
                await page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.08, 0.2))

            await element.type(char, delay=0)
            delay_ms = random.randint(_TYPING_DELAY_MIN_MS, _TYPING_DELAY_MAX_MS)

            # Burst: sometimes type 2-4 chars fast (like a fast typist)
            if random.random() < 0.3:
                delay_ms = random.randint(20, 50)

            # Word boundary pause: longer after space
            if char == " ":
                delay_ms += random.randint(50, 200)

            await asyncio.sleep(delay_ms / 1000.0)
            i += 1

    # ── Submit ────────────────────────────────────────────────────────────────

    async def _click_submit(
        self, page: "Page", timeout_ms: int = 10_000
    ) -> bool:
        """
        Locate and click the form's submit button.
        Returns True if submit button was found and clicked.
        """
        for sel in GOOGLE_FORM_SUBMIT:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    if self._mouse is not None:
                        box = await btn.bounding_box()
                        if box:
                            await self._mouse.click(
                                page,
                                box["x"] + box["width"] / 2,
                                box["y"] + box["height"] / 2,
                            )
                            logger.info("[GForm/Bypass] Submit clicked via %s", sel)
                            return True
                    await btn.click()
                    logger.info("[GForm/Bypass] Submit clicked via %s", sel)
                    return True
            except Exception:
                continue

        logger.error("[GForm/Bypass] No submit button found")
        return False

    # ── Pre-fill behavior ─────────────────────────────────────────────────────

    async def _pre_fill_prime(self, page: "Page") -> None:
        """
        Idle + scroll the form page before filling — builds reCAPTCHA v3 trust score.
        """
        dwell = random.uniform(self.MIN_PRE_FILL_DWELL, self.MAX_PRE_FILL_DWELL)
        logger.debug("[GForm/Bypass] Pre-fill prime: %.1fs dwell", dwell)

        await asyncio.sleep(random.uniform(1.0, 2.0))

        # Gentle scroll down the form
        try:
            steps = random.randint(2, 5)
            for _ in range(steps):
                dy = random.randint(100, 300)
                await page.evaluate(f"window.scrollBy(0, {dy})")
                await asyncio.sleep(random.uniform(0.4, 1.0))
        except Exception:
            pass

        remaining = max(0, dwell - 2.0)
        await asyncio.sleep(remaining)

    # ── Honeypot detection ────────────────────────────────────────────────────

    @staticmethod
    async def _is_honeypot(element: "ElementHandle") -> bool:
        """
        Return True if `element` is a honeypot (hidden from real users).
        Checks inline style for display:none, visibility:hidden, etc.
        """
        try:
            style = await element.get_attribute("style") or ""
            if re.search(r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0", style, re.IGNORECASE):
                return True
            # aria-hidden
            aria = await element.get_attribute("aria-hidden") or ""
            if aria.lower() == "true":
                return True
            # Check computed visibility
            visible = await element.is_visible()
            return not visible
        except Exception:
            return False
