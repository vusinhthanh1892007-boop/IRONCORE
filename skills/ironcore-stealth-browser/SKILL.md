---
name: ironcore-stealth-browser
version: 1.0.0
description: |
  Launch a stealth Playwright browser that masks bot fingerprints: spoofs Canvas,
  WebGL, Audio, Battery, GPU, Font, navigator.webdriver, hardware concurrency,
  language, timezone, and WebRTC. Includes human-like mouse movement (Bezier +
  Fitts's Law) and session/profile rotation. Community Edition (CE) — no license
  required. Use when scraping sites with basic bot detection, running automated
  browser tasks without getting flagged, or testing fingerprint evasion.
metadata: {"openclaw": {"emoji": "🕵️", "requires": {"bins": ["python3"], "packages": ["playwright", "pydantic"]}}}
---

# IronCore Stealth Browser

Stealth Playwright browser with production-grade fingerprint spoofing and human-like behaviour.
Part of the [IronCore Browser Module](https://github.com/ironcore-paid) — Community Edition.

## When to use
- Scraping any site that detects `navigator.webdriver` or headless Chrome
- Automating form fills, clicks, screenshots while avoiding bot flags
- Rotating browser profiles to prevent session-based tracking
- Testing your own site's anti-bot hardening

---

## Core classes

| Class | File | Purpose |
|---|---|---|
| `BrowserProfile` | `stealth.py` | Pydantic model: UA, viewport, locale, TZ, WebGL vendor/renderer, canvas seed |
| `FingerprintSpoofer` | `stealth.py` | Injects JS init scripts for basic spoofing |
| `StealthBrowser` | `stealth.py` | High-level async browser context with stealth applied |
| `FullFingerprintSpoofer` | `fingerprint_spoofer.py` | Full 7-vector JS spoofing: Canvas+WebGL+Audio+Battery+GPU+Font+Misc |
| `DeviceFingerprint` | `fingerprint_spoofer.py` | Library of 100+ real device profiles |
| `MouseEngine` | `mouse_engine.py` | Human-like mouse: Bezier curves, Fitts's Law, micro-jitter, drag |
| `SessionManager` | `session_manager.py` | Persist + reload browser sessions (cookies / localStorage) |
| `ProfilePool` | `session_manager.py` | Pool of profiles, auto-rotate, flag flagged ones |
| `ProfileWarmUp` | `session_manager.py` | Warm-up fresh profiles with realistic browsing history |

---

## Quick start — stealth navigate & screenshot

```python
python3 << 'EOF'
import asyncio
from ironcore.browser.stealth import StealthBrowser, BrowserProfile

PROFILE = BrowserProfile(
    profile_id="demo",
    name="Chrome 124 / Win11",
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    viewport=(1366, 768),
    locale="en-US",
    timezone="America/New_York",
    platform="Win32",
    webgl_vendor="Google Inc. (NVIDIA)",
    webgl_renderer="ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)",
    canvas_noise_seed=42,
)

TARGET_URL = "https://TARGET_URL_HERE"  # REPLACE

async def main():
    async with StealthBrowser(PROFILE) as browser:
        result = await browser.navigate(TARGET_URL)
        print(f"Status : {result.status_code}")
        print(f"URL    : {result.url}")
        content = await browser.get_content()
        print(f"Content: {content[:500]}")
        b64 = await browser.screenshot_b64()
        print(f"Screenshot: {len(b64)} bytes (base64)")

asyncio.run(main())
EOF
```

---

## Full fingerprint spoofing (Phase 5 — 7 vectors)

```python
python3 << 'EOF'
import asyncio
from playwright.async_api import async_playwright
from ironcore.browser.stealth import BrowserProfile
from ironcore.browser.fingerprint_spoofer import FullFingerprintSpoofer, get_device_fingerprint

# Pick a pre-built real device profile (100+ available)
device = get_device_fingerprint("chrome_win11_rtx3060")   # or get_random_browser_profile()
profile = device.to_browser_profile()

spoofer = FullFingerprintSpoofer(profile)
scripts = spoofer.generate_all_scripts()   # returns list[str] of JS init scripts

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=profile.user_agent,
            viewport={"width": profile.viewport[0], "height": profile.viewport[1]},
            locale=profile.locale,
            timezone_id=profile.timezone,
        )
        for script in scripts:
            await ctx.add_init_script(script=script)
        page = await ctx.new_page()
        await page.goto("https://TARGET_URL_HERE")  # REPLACE
        print(await page.title())
        await browser.close()

asyncio.run(main())
EOF
```

---

## Human-like mouse movement

```python
python3 << 'EOF'
import asyncio
from playwright.async_api import async_playwright
from ironcore.browser.mouse_engine import MouseEngine

TARGET_URL = "https://TARGET_URL_HERE"   # REPLACE
CLICK_X, CLICK_Y = 640, 400             # REPLACE with element coords

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(TARGET_URL)

        mouse = MouseEngine()
        await mouse.move_to(page, CLICK_X, CLICK_Y)   # natural acceleration + tremor
        await mouse.click(page, CLICK_X, CLICK_Y)
        # await mouse.drag(page, (100, 200), (300, 200))   # for sliders
        await browser.close()

asyncio.run(main())
EOF
```

---

## Session/profile pool with rotation

```python
python3 << 'EOF'
import asyncio
from playwright.async_api import async_playwright
from ironcore.browser.session_manager import SessionManager, ProfilePool
from ironcore.browser.fingerprint_spoofer import DEVICE_FINGERPRINT_LIBRARY

TARGET_URL = "https://TARGET_URL_HERE"   # REPLACE

async def main():
    # Build pool from device library (auto-rotate every 50 requests)
    pool = ProfilePool(
        profiles=[d.to_browser_profile() for d in DEVICE_FINGERPRINT_LIBRARY[:5]],
        max_uses_per_profile=50,
    )
    await pool.initialize()

    profile = await pool.get_next_profile()
    session = SessionManager(profile)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await session.create_context(browser)
        page = await ctx.new_page()
        await page.goto(TARGET_URL)
        await session.save(ctx)     # persist cookies for next run
        print("Done:", await page.title())
        await browser.close()

asyncio.run(main())
EOF
```

---

## Steps (how the AI should use this skill)

1. Parse the user's request: URL, action (navigate/click/fill/screenshot), any element selectors
2. Choose a `BrowserProfile` — use `get_random_browser_profile()` if no preference given
3. Use `StealthBrowser` for simple tasks, raw `FullFingerprintSpoofer` + `MouseEngine` for advanced
4. If repeated visits needed, wrap in `SessionManager` / `ProfilePool`
5. Report: status code, page title, first 500 chars of content, or screenshot path

## Prerequisites

```bash
pip install playwright pydantic pillow numpy
python3 -m playwright install chromium
```

## Notes
- `webrtc_disabled=True` is default (prevents IP leak via STUN)
- `canvas_noise_seed` must be consistent per profile — stored in `BrowserProfile`
- For Cloudflare / DataDome sites, use `ironcore-bot-bypass` skill instead
- For CAPTCHA challenges, combine with `ironcore-captcha-solver` skill
