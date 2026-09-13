---
name: ironcore-bot-bypass
version: 1.0.0
description: |
  Bypass advanced bot-detection systems: Cloudflare (JS challenge, Turnstile,
  rate-limit 429), DataDome, Reddit anti-bot, and Google Forms protection.
  Includes BotDetectionEvasion orchestrator that auto-detects which system is
  active and routes to the correct bypass with profile rotation and 3-retry logic.
  Enterprise Edition (EE) — requires IRONCORE_EDITION=enterprise.
  Use when a site uses Cloudflare, DataDome, or platform-specific bot protection.
metadata: {"openclaw": {"emoji": "🛡️", "requires": {"bins": ["python3"], "packages": ["playwright", "pydantic"]}, "edition": "enterprise"}}
---

# IronCore Bot Bypass

Auto-detect and bypass Cloudflare, DataDome, Reddit, and Google Forms bot protection.
Part of the [IronCore Browser Module](https://github.com/ironcore-paid) — **Enterprise Edition**.

## When to use
- Target site shows Cloudflare "Checking your browser" / Turnstile widget
- Site returns 403/429 with DataDome block page
- Scraping Reddit and getting bot-wall redirects
- Automating Google Forms that use bot detection
- Unknown protection — let `BotDetectionEvasion` auto-detect and route

## License
Set `IRONCORE_EDITION=enterprise` before running:
```bash
export IRONCORE_EDITION=enterprise
```

---

## Core classes

| Class | File | Purpose |
|---|---|---|
| `BotDetectionEvasion` | `bot_evasion.py` | **Orchestrator**: detect → route → retry × 3 with profile rotation |
| `ChallengeType` | `bot_evasion.py` | Constants: `CLOUDFLARE`, `DATADOME`, `REDDIT`, `GOOGLE_FORM`, `UNKNOWN` |
| `BypassResult` | `bot_evasion.py` | Result: `success`, `challenge_type`, `attempts`, `error` |
| `CloudflareDetector` | `cloudflare_bypass.py` | Detect CF JS challenge / Turnstile / clearance cookie |
| `CloudflareBypass` | `cloudflare_bypass.py` | Bypass CF JS challenge + Turnstile widget |
| `CloudflareRateLimitHandler` | `cloudflare_bypass.py` | Handle 429 / 1020 with exponential back-off |
| `DataDomeDetector` | `datadome_bypass.py` | Detect DataDome block page + block type |
| `DataDomeBypass` | `datadome_bypass.py` | Prime behavioral signals to pass DataDome |
| `RedditDetector` | `reddit_bypass.py` | Detect Reddit anti-bot challenge |
| `RedditBypass` | `reddit_bypass.py` | Bypass Reddit anti-bot |
| `GoogleFormDetector` | `google_form_bypass.py` | Detect Google Forms bot check |
| `GoogleFormBypass` | `google_form_bypass.py` | Bypass Google Forms protection |

---

## Recommended: BotDetectionEvasion orchestrator (auto-routing)

The easiest way — let the orchestrator figure out which system is blocking.

```python
python3 << 'EOF'
import asyncio, os
os.environ["IRONCORE_EDITION"] = "enterprise"   # required for EE

from playwright.async_api import async_playwright
from ironcore.browser.stealth import StealthBrowser
from ironcore.browser.mouse_engine import MouseEngine
from ironcore.browser.fingerprint_spoofer import get_random_browser_profile
from ironcore.browser.bot_evasion import BotDetectionEvasion

TARGET_URL = "https://TARGET_URL_HERE"  # REPLACE

async def main():
    profile = get_random_browser_profile()
    mouse = MouseEngine()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            user_agent=profile.user_agent,
            viewport={"width": profile.viewport[0], "height": profile.viewport[1]},
        )
        page = await ctx.new_page()

        evasion = BotDetectionEvasion(mouse_engine=mouse)

        # Prime before navigation (behavioral warm-up)
        await evasion.pre_request_prime(page)
        await page.goto(TARGET_URL, wait_until="domcontentloaded")

        # Auto-detect + bypass
        result = await evasion.handle_challenge(page)

        if result.success:
            print(f"✅ Bypassed {result.challenge_type} in {result.attempts} attempt(s)")
            print(f"Page title: {await page.title()}")
        else:
            print(f"❌ Failed to bypass {result.challenge_type}: {result.error}")

        await browser.close()

asyncio.run(main())
EOF
```

---

## Cloudflare bypass (explicit)

Use when you **know** the site uses Cloudflare.

```python
python3 << 'EOF'
import asyncio, os
os.environ["IRONCORE_EDITION"] = "enterprise"

from playwright.async_api import async_playwright
from ironcore.browser.mouse_engine import MouseEngine
from ironcore.browser.cloudflare_bypass import CloudflareDetector, CloudflareBypass, CloudflareRateLimitHandler

TARGET_URL = "https://TARGET_URL_HERE"  # REPLACE

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(TARGET_URL, wait_until="domcontentloaded")

        detector = CloudflareDetector()
        if await detector.is_cloudflare_challenge(page):
            cf_type = await detector.detect_challenge_type(page)
            print(f"Cloudflare type: {cf_type}")

            mouse = MouseEngine()
            bypass = CloudflareBypass(mouse_engine=mouse)

            if cf_type == "turnstile":
                await bypass.bypass_turnstile(page)
            else:
                await bypass.bypass_js_challenge(page)

            # Check clearance cookie
            if await detector.has_clearance_cookie(page):
                print("✅ cf_clearance cookie obtained")

        # Handle 429 rate-limit
        rl_handler = CloudflareRateLimitHandler()
        # await rl_handler.wait_and_retry(page, TARGET_URL)  # uncomment if needed

        print("Title:", await page.title())
        await browser.close()

asyncio.run(main())
EOF
```

---

## DataDome bypass

```python
python3 << 'EOF'
import asyncio, os
os.environ["IRONCORE_EDITION"] = "enterprise"

from playwright.async_api import async_playwright
from ironcore.browser.mouse_engine import MouseEngine
from ironcore.browser.datadome_bypass import DataDomeDetector, DataDomeBypass

TARGET_URL = "https://TARGET_URL_HERE"  # REPLACE

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(TARGET_URL, wait_until="domcontentloaded")

        if await DataDomeDetector.is_blocked(page):
            block_type = await DataDomeDetector.detect_block_type(page)
            print(f"DataDome block type: {block_type}")

            mouse = MouseEngine()
            bypass = DataDomeBypass(mouse_engine=mouse)
            await bypass.prime_behavioral_signals(page, duration_seconds=10)
            print("Behavioral signals primed — reloading...")
            await page.reload()

        print("Title:", await page.title())
        await browser.close()

asyncio.run(main())
EOF
```

---

## Reddit bypass

```python
python3 << 'EOF'
import asyncio, os
os.environ["IRONCORE_EDITION"] = "enterprise"

from playwright.async_api import async_playwright
from ironcore.browser.mouse_engine import MouseEngine
from ironcore.browser.reddit_bypass import RedditDetector, RedditBypass

REDDIT_URL = "https://www.reddit.com/r/SUBREDDIT_HERE"  # REPLACE

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(REDDIT_URL, wait_until="domcontentloaded")

        if await RedditDetector.is_blocked(page):
            print("Reddit anti-bot detected — bypassing...")
            mouse = MouseEngine()
            bypass = RedditBypass(mouse_engine=mouse)
            await bypass.bypass(page)
        
        print("Title:", await page.title())
        await browser.close()

asyncio.run(main())
EOF
```

---

## Google Form bypass

```python
python3 << 'EOF'
import asyncio, os
os.environ["IRONCORE_EDITION"] = "enterprise"

from playwright.async_api import async_playwright
from ironcore.browser.mouse_engine import MouseEngine
from ironcore.browser.google_form_bypass import GoogleFormDetector, GoogleFormBypass

FORM_URL = "https://docs.google.com/forms/d/FORM_ID_HERE/viewform"  # REPLACE

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(FORM_URL, wait_until="domcontentloaded")

        if await GoogleFormDetector.is_protected(page):
            print("Google Form bot check detected — bypassing...")
            mouse = MouseEngine()
            bypass = GoogleFormBypass(mouse_engine=mouse)
            await bypass.bypass(page)
        
        print("Form accessible:", await page.title())
        await browser.close()

asyncio.run(main())
EOF
```

---

## Detect-only (no bypass yet)

```python
python3 << 'EOF'
import asyncio, os
os.environ["IRONCORE_EDITION"] = "enterprise"

from playwright.async_api import async_playwright
from ironcore.browser.bot_evasion import BotDetectionEvasion
from ironcore.browser.mouse_engine import MouseEngine

TARGET_URL = "https://TARGET_URL_HERE"  # REPLACE

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(TARGET_URL, wait_until="domcontentloaded")

        mouse = MouseEngine()
        evasion = BotDetectionEvasion(mouse_engine=mouse)
        challenge = await evasion.detect(page)
        print(f"Detected challenge type: {challenge}")   # e.g. "cloudflare", "datadome", "none"
        await browser.close()

asyncio.run(main())
EOF
```

---

## Steps

1. Set `IRONCORE_EDITION=enterprise` in environment
2. Open the page with a stealth browser (see `ironcore-stealth-browser`) to reduce initial detection
3. Check if the site has a known protection:
   - Use `BotDetectionEvasion` orchestrator for unknown sites (auto-routes)
   - Use explicit detector/bypass classes for known platforms
4. Call `pre_request_prime()` before navigation to build behavioral history
5. After bypass, verify with `has_clearance_cookie()` (CF) or page title change
6. Combine with `ironcore-captcha-solver` if a CAPTCHA appears after bypass

## Prerequisites

```bash
export IRONCORE_EDITION=enterprise
pip install playwright pydantic
python3 -m playwright install chromium
```

## Notes
- `BotDetectionEvasion` retries up to **3 times** with profile rotation between attempts
- `CloudflareRateLimitHandler` uses exponential back-off on 429 / 1020 responses
- DataDome bypass works via **behavioral priming** — no token cracking
- Reddit/GForm bypasses depend on site-specific heuristics; update if site changes
- This module is **Enterprise Edition only** — CE users get `None` for all EE classes
