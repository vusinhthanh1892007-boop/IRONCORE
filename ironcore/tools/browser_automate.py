"""
IronCore Tool: browser_automate
================================
Automate a real browser using Playwright: navigate, click, fill forms,
take screenshots, extract text. Enables AI to interact with any website.

Requirements: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)

# ── Allowed action types ──────────────────────────────────────────────────
_ALLOWED_ACTIONS = {
    "navigate", "click", "fill", "select", "check", "uncheck",
    "press", "wait", "screenshot", "get_text", "get_html",
    "scroll", "hover", "clear", "get_url", "get_title",
    "wait_for_selector", "wait_for_navigation",
}

# ── SSRF guard: blocked URL patterns ─────────────────────────────────────
_BLOCKED_URL_PATTERNS = [
    r"^file://",
    r"^ftp://",
    r"169\.254\.",        # link-local (AWS metadata)
    r"100\.64\.",         # RFC 6598 shared address space
]

def _is_url_allowed(url: str) -> bool:
    """SSRF protection: block file://, ftp://, and cloud metadata IPs."""
    for pat in _BLOCKED_URL_PATTERNS:
        if re.search(pat, url, re.IGNORECASE):
            return False
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False
        if host.endswith(".local"):
            return False
    except Exception:
        return False
    return True


# ── Common browser profile paths ─────────────────────────────────────────
_PROFILE_DIRS = {
    # Chrome on Linux
    "chrome": [
        Path.home() / ".config" / "google-chrome",
        Path.home() / ".config" / "google-chrome-stable",
    ],
    # Chromium on Linux
    "chromium": [
        Path.home() / ".config" / "chromium",
    ],
    # Firefox on Linux
    "firefox": [
        Path.home() / ".mozilla" / "firefox",
    ],
}


def _resolve_profile_dir(user_data_dir: str, browser_type: str) -> Optional[str]:
    """
    Resolve the profile directory.
    - "auto" → detect the default profile for the given browser
    - Any other value → treat as literal path
    Returns None if not found.
    """
    if user_data_dir.strip().lower() not in ("", "auto", "none"):
        p = Path(user_data_dir).expanduser()
        return str(p) if p.exists() else None

    if user_data_dir.strip().lower() != "auto":
        return None

    # Auto-detect
    candidates = _PROFILE_DIRS.get(browser_type.lower(), [])
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _make_profile_copy(src: str) -> str:
    """
    Copy the browser profile to a temp directory so we don't conflict
    with a running browser instance that has the profile locked.
    """
    tmp = tempfile.mkdtemp(prefix="ironcore_browser_")
    dst = os.path.join(tmp, "profile")
    try:
        shutil.copytree(src, dst, symlinks=True,
                        ignore=shutil.ignore_patterns("SingletonLock", "*.lock", "lockfile"))
        return dst
    except Exception as exc:
        logger.warning("Profile copy failed (%s), using original dir: %s", exc, src)
        shutil.rmtree(tmp, ignore_errors=True)
        return src


@skill(
    name="browser_automate",
    version="2.0.0",
    description=(
        "Automate a real web browser: navigate to URLs, click elements, fill forms, "
        "take screenshots, extract text. Supports using your existing Chrome/Firefox "
        "profile (already logged-in sessions). Set user_data_dir='auto' to reuse your "
        "browser's saved logins and cookies automatically."
    ),
    author="brain",
    tags=["browser", "automation", "playwright", "web", "click", "form", "screenshot", "login"],
    risk_level=RiskLevel.HIGH,
    requires_network=True,
    parameters=[
        SkillParameterSchema(
            name="actions",
            type="list",
            description=(
                "List of browser actions to execute in order. Each action is a dict with 'type' and optional fields.\n"
                "Action types:\n"
                "  navigate:         {type, url}  — Go to a URL\n"
                "  click:            {type, selector}  — Click an element (CSS or text=... selector)\n"
                "  fill:             {type, selector, value}  — Type text into input\n"
                "  select:           {type, selector, value}  — Choose option from <select>\n"
                "  press:            {type, selector, key}  — Press keyboard key (e.g. 'Enter', 'Tab')\n"
                "  check:            {type, selector}  — Check a checkbox\n"
                "  uncheck:          {type, selector}  — Uncheck a checkbox\n"
                "  wait:             {type, ms}  — Wait N milliseconds\n"
                "  wait_for_selector:{type, selector, timeout_ms}  — Wait until element appears\n"
                "  screenshot:       {type, full_page}  — Take screenshot (returns base64 PNG)\n"
                "  get_text:         {type, selector}  — Extract visible text from element\n"
                "  get_html:         {type, selector, max_length}  — Get inner HTML\n"
                "  get_url:          {type}  — Get current URL\n"
                "  get_title:        {type}  — Get page title\n"
                "  scroll:           {type, direction, amount_px}  — Scroll page\n"
                "  hover:            {type, selector}  — Hover over element\n"
                "  clear:            {type, selector}  — Clear input field"
            ),
            required=True,
        ),
        SkillParameterSchema(
            name="browser_type",
            type="string",
            description="Browser to use: 'chromium' (default), 'chrome' (system Chrome), 'firefox'.",
            required=False,
            default="chromium",
        ),
        SkillParameterSchema(
            name="user_data_dir",
            type="string",
            description=(
                "Path to existing browser profile directory to inherit saved logins/cookies. "
                "Use 'auto' to auto-detect your default Chrome/Firefox profile. "
                "Leave empty for a fresh private session (no saved logins)."
            ),
            required=False,
            default="",
        ),
        SkillParameterSchema(
            name="headless",
            type="bool",
            description="Run browser invisibly in background. Default True. Set False to watch it work.",
            required=False,
            default=True,
        ),
        SkillParameterSchema(
            name="timeout_ms",
            type="int",
            description="Default timeout per action in milliseconds (500-30000). Default 8000.",
            required=False,
            default=8000,
        ),
        SkillParameterSchema(
            name="viewport_width",
            type="int",
            description="Browser viewport width in pixels. Default 1280.",
            required=False,
            default=1280,
        ),
        SkillParameterSchema(
            name="viewport_height",
            type="int",
            description="Browser viewport height in pixels. Default 720.",
            required=False,
            default=720,
        ),
    ],
)
async def browser_automate(
    actions: List[Dict[str, Any]],
    browser_type: str = "chromium",
    user_data_dir: str = "",
    headless: bool = True,
    timeout_ms: int = 8000,
    viewport_width: int = 1280,
    viewport_height: int = 720,
) -> Dict[str, Any]:
    """Execute a sequence of browser actions using Playwright."""
    try:
        from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        return {
            "error": (
                "Playwright is not installed. "
                "Run: pip install playwright && playwright install chromium"
            )
        }

    if not isinstance(actions, list) or not actions:
        return {"error": "actions must be a non-empty list of action dicts"}

    timeout_ms = max(500, min(30_000, int(timeout_ms)))
    browser_type = (browser_type or "chromium").strip().lower()
    if browser_type not in ("chromium", "chrome", "firefox"):
        browser_type = "chromium"

    results: List[Dict[str, Any]] = []
    screenshots: List[str] = []
    errors: List[str] = []
    _tmp_profile_dir: Optional[str] = None

    # Resolve profile directory
    resolved_profile = _resolve_profile_dir(user_data_dir, browser_type)
    if resolved_profile:
        # Copy profile to temp dir to avoid SingletonLock conflicts
        # (browser might be currently running)
        _tmp_profile_dir = _make_profile_copy(resolved_profile)
        logger.info("Using browser profile copy: %s → %s", resolved_profile, _tmp_profile_dir)
    else:
        _tmp_profile_dir = None

    launch_args = ["--no-sandbox", "--disable-setuid-sandbox"]
    viewport = {"width": int(viewport_width), "height": int(viewport_height)}
    ua = (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )

    async with async_playwright() as p:
        # Select browser engine
        if browser_type == "firefox":
            engine = p.firefox
        else:
            engine = p.chromium

        if _tmp_profile_dir:
            # launch_persistent_context: uses existing profile with cookies/session
            launch_kwargs: Dict[str, Any] = {
                "headless": headless,
                "viewport": viewport,
                "args": launch_args if browser_type != "firefox" else [],
            }
            if browser_type == "chrome":
                launch_kwargs["channel"] = "chrome"
            context = await engine.launch_persistent_context(
                _tmp_profile_dir,
                **launch_kwargs,
            )
            browser = None  # persistent context doesn't expose a browser object
        else:
            # Fresh session — no profile
            launch_kwargs = {
                "headless": headless,
                "args": launch_args if browser_type != "firefox" else [],
            }
            if browser_type == "chrome":
                launch_kwargs["channel"] = "chrome"
            browser = await engine.launch(**launch_kwargs)
            context = await browser.new_context(
                viewport=viewport,
                user_agent=ua,
            )

        page = await context.new_page()

        for idx, action in enumerate(actions):
            if not isinstance(action, dict):
                errors.append(f"Action #{idx}: must be a dict, got {type(action).__name__}")
                continue

            action_type = str(action.get("type", "")).strip()
            step_result: Dict[str, Any] = {"step": idx, "type": action_type}

            if action_type not in _ALLOWED_ACTIONS:
                errors.append(f"Action #{idx}: unknown type '{action_type}'. Allowed: {sorted(_ALLOWED_ACTIONS)}")
                continue

            try:
                if action_type == "navigate":
                    url = str(action.get("url", ""))
                    if not _is_url_allowed(url):
                        errors.append(f"Action #{idx}: URL '{url}' is blocked for security reasons")
                        continue
                    await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                    step_result["url"] = page.url
                    step_result["title"] = await page.title()

                elif action_type == "click":
                    sel = str(action.get("selector", ""))
                    # Support text-based selectors like "text=Submit"
                    if sel.startswith("text="):
                        await page.get_by_text(sel[5:]).first.click(timeout=timeout_ms)
                    else:
                        await page.locator(sel).first.click(timeout=timeout_ms)
                    step_result["clicked"] = sel

                elif action_type == "fill":
                    sel = str(action.get("selector", ""))
                    val = str(action.get("value", ""))
                    await page.locator(sel).first.fill(val, timeout=timeout_ms)
                    step_result["filled"] = sel

                elif action_type == "select":
                    sel = str(action.get("selector", ""))
                    val = str(action.get("value", ""))
                    await page.locator(sel).first.select_option(val, timeout=timeout_ms)
                    step_result["selected"] = val

                elif action_type == "press":
                    sel = str(action.get("selector", ""))
                    key = str(action.get("key", "Enter"))
                    if sel:
                        await page.locator(sel).first.press(key, timeout=timeout_ms)
                    else:
                        await page.keyboard.press(key)
                    step_result["pressed"] = key

                elif action_type == "check":
                    sel = str(action.get("selector", ""))
                    await page.locator(sel).first.check(timeout=timeout_ms)

                elif action_type == "uncheck":
                    sel = str(action.get("selector", ""))
                    await page.locator(sel).first.uncheck(timeout=timeout_ms)

                elif action_type == "wait":
                    ms = int(action.get("ms", 1000))
                    await asyncio.sleep(ms / 1000)
                    step_result["waited_ms"] = ms

                elif action_type == "wait_for_selector":
                    sel = str(action.get("selector", ""))
                    t = int(action.get("timeout_ms", timeout_ms))
                    await page.wait_for_selector(sel, timeout=t)
                    step_result["found"] = sel

                elif action_type == "screenshot":
                    full = bool(action.get("full_page", False))
                    img_bytes = await page.screenshot(full_page=full)
                    b64 = base64.b64encode(img_bytes).decode()
                    screenshots.append(b64)
                    step_result["screenshot_index"] = len(screenshots) - 1
                    step_result["size_bytes"] = len(img_bytes)

                elif action_type == "get_text":
                    sel = str(action.get("selector", "body"))
                    text = await page.locator(sel).first.inner_text(timeout=timeout_ms)
                    step_result["text"] = text[:4000]  # Limit output

                elif action_type == "get_html":
                    sel = str(action.get("selector", "body"))
                    max_len = int(action.get("max_length", 4000))
                    html = await page.locator(sel).first.inner_html(timeout=timeout_ms)
                    step_result["html"] = html[:max_len]

                elif action_type == "get_url":
                    step_result["url"] = page.url

                elif action_type == "get_title":
                    step_result["title"] = await page.title()

                elif action_type == "scroll":
                    direction = str(action.get("direction", "down"))
                    amount = int(action.get("amount_px", 500))
                    if direction == "down":
                        await page.evaluate(f"window.scrollBy(0, {amount})")
                    elif direction == "up":
                        await page.evaluate(f"window.scrollBy(0, -{amount})")
                    elif direction == "right":
                        await page.evaluate(f"window.scrollBy({amount}, 0)")
                    elif direction == "left":
                        await page.evaluate(f"window.scrollBy(-{amount}, 0)")
                    step_result["scrolled"] = f"{direction} {amount}px"

                elif action_type == "hover":
                    sel = str(action.get("selector", ""))
                    await page.locator(sel).first.hover(timeout=timeout_ms)

                elif action_type == "clear":
                    sel = str(action.get("selector", ""))
                    await page.locator(sel).first.clear(timeout=timeout_ms)

                step_result["ok"] = True

            except PlaywrightTimeout as exc:
                step_result["ok"] = False
                step_result["error"] = f"Timeout after {timeout_ms}ms: {exc}"
                errors.append(f"Step {idx} ({action_type}): timeout")
            except Exception as exc:
                step_result["ok"] = False
                step_result["error"] = str(exc)
                errors.append(f"Step {idx} ({action_type}): {exc}")

            results.append(step_result)

        final_url = page.url
        final_title = await page.title()

        if browser:
            await browser.close()
        else:
            await context.close()  # persistent context

    # Clean up temp profile copy
    if _tmp_profile_dir and _tmp_profile_dir != resolved_profile:
        parent = str(Path(_tmp_profile_dir).parent)
        shutil.rmtree(parent, ignore_errors=True)
        logger.debug("Cleaned up temp profile dir: %s", parent)

    profile_used = resolved_profile or "fresh session (no profile)"

    return {
        "steps": results,
        "final_url": final_url,
        "final_title": final_title,
        "screenshots": screenshots,   # list of base64 PNG strings
        "errors": errors,
        "total_steps": len(actions),
        "successful_steps": sum(1 for r in results if r.get("ok")),
        "browser_type": browser_type,
        "profile_used": profile_used,
    }
