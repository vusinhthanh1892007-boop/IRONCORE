---
name: ironcore-captcha-solver
version: 1.0.0
description: |
  Solve CAPTCHA challenges automatically using computer vision (OpenCV) and VLM
  assistance. Supports GeeTest v3 slider/puzzle, reCAPTCHA v2 image tiles, and
  reCAPTCHA v3 score priming. Community Edition (CE) — no license required.
  Use when a page presents a CAPTCHA that blocks automation.
metadata: {"openclaw": {"emoji": "🔐", "requires": {"bins": ["python3"], "packages": ["playwright", "opencv-python-headless", "numpy", "pydantic"]}}}
---

# IronCore CAPTCHA Solver

Automated CAPTCHA solving with OpenCV template matching and optional VLM fallback.
Part of the [IronCore Browser Module](https://github.com/ironcore-paid) — Community Edition.

## When to use
- Page shows a GeeTest slider or puzzle CAPTCHA
- Page shows reCAPTCHA v2 image tile challenges ("select all traffic lights")
- Page uses reCAPTCHA v3 — need to prime behavioral signals to get a high score
- Any automation flow that gets blocked by a CAPTCHA wall

---

## Core classes

| Class | File | Purpose |
|---|---|---|
| `GeeTestSolver` | `captcha_solver.py` | Solve GeeTest v3: screenshot → OpenCV edge detection → Bezier drag |
| `GeeTestSolverResult` | `captcha_solver.py` | Result model: `success`, `offset_px`, `attempts`, `screenshot_b64` |
| `OpenCVSolver` | `captcha_solver.py` | Low-level: Canny edge detect, `find_slider_offset()` |
| `ReCaptchaV2Solver` | `captcha_solver.py` | Solve reCAPTCHA v2: tile screenshot → VLM picks correct tiles → click |
| `ReCaptchaV3Analyzer` | `captcha_solver.py` | Prime v3 score: simulate scrolling + mouse to push score above 0.7 |
| `TileCoordinateMapper` | `captcha_solver.py` | Map tile grid indices → absolute page coordinates |

---

## GeeTest v3 solver (slider puzzle)

```python
python3 << 'EOF'
import asyncio
from playwright.async_api import async_playwright
from ironcore.browser.stealth import StealthBrowser, BrowserProfile
from ironcore.browser.mouse_engine import MouseEngine
from ironcore.browser.captcha_solver import GeeTestSolver
from ironcore.browser.fingerprint_spoofer import get_random_browser_profile

TARGET_URL = "https://TARGET_URL_HERE"  # REPLACE — page that shows GeeTest

async def main():
    profile = get_random_browser_profile()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            user_agent=profile.user_agent,
            viewport={"width": profile.viewport[0], "height": profile.viewport[1]},
        )
        page = await ctx.new_page()
        await page.goto(TARGET_URL)

        mouse = MouseEngine()
        solver = GeeTestSolver(mouse_engine=mouse)
        result = await solver.solve(page)

        if result.success:
            print(f"✅ GeeTest solved! offset={result.offset_px}px, attempts={result.attempts}")
        else:
            print(f"❌ Failed after {result.attempts} attempts — error: {result.error}")

        await browser.close()

asyncio.run(main())
EOF
```

---

## reCAPTCHA v2 solver (image tiles)

> **Requires VLM bridge** — pass a VLM object that has `.ask_image(image_bytes, prompt) -> str`

```python
python3 << 'EOF'
import asyncio
from playwright.async_api import async_playwright
from ironcore.browser.mouse_engine import MouseEngine
from ironcore.browser.captcha_solver import ReCaptchaV2Solver

TARGET_URL = "https://TARGET_URL_HERE"  # REPLACE

# Minimal VLM stub — replace with real VLM (e.g. ironcore VLMBridge)
class SimpleVLM:
    async def ask_image(self, image_bytes: bytes, prompt: str) -> str:
        # REPLACE: call your VLM and return comma-separated tile indices e.g. "0,3,6"
        return "0,3,6"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(TARGET_URL)

        mouse = MouseEngine()
        vlm = SimpleVLM()
        solver = ReCaptchaV2Solver(mouse_engine=mouse, vlm_bridge=vlm)
        result = await solver.solve(page, max_attempts=3)

        if result.success:
            print(f"✅ reCAPTCHA v2 solved in {result.attempts} attempts")
        else:
            print(f"❌ Failed — score: {result.score}")

        await browser.close()

asyncio.run(main())
EOF
```

---

## reCAPTCHA v3 — prime behavioral signals

reCAPTCHA v3 scores based on mouse/scroll behaviour. Use `ReCaptchaV3Analyzer` **before** submitting a form to push the score above 0.7.

```python
python3 << 'EOF'
import asyncio
from playwright.async_api import async_playwright
from ironcore.browser.mouse_engine import MouseEngine
from ironcore.browser.captcha_solver import ReCaptchaV3Analyzer

TARGET_URL = "https://TARGET_URL_HERE"  # REPLACE

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(TARGET_URL)

        mouse = MouseEngine()
        analyzer = ReCaptchaV3Analyzer(mouse_engine=mouse)

        # Prime: will scroll + move mouse for ~5-10s to build a good score
        await analyzer.prime_behavioral_signals(page, duration_seconds=8)

        risk = analyzer.assess_action_score_risk()
        print(f"Estimated risk level: {risk}")  # "low" / "medium" / "high"

        # Now submit your form or trigger the action protected by v3
        await page.click("button[type=submit]")
        await browser.close()

asyncio.run(main())
EOF
```

---

## Using OpenCV solver directly (custom CAPTCHA)

```python
python3 << 'EOF'
import urllib.request
from ironcore.browser.captcha_solver import OpenCVSolver

# Load background and piece images as bytes
with open("bg.png", "rb") as f:
    bg_bytes = f.read()
with open("piece.png", "rb") as f:
    piece_bytes = f.read()

# Find the pixel offset where the piece fits
bg_img = OpenCVSolver.preprocess_image(bg_bytes)
piece_img = OpenCVSolver.preprocess_image(piece_bytes)
bg_edge = OpenCVSolver.apply_canny(bg_img)
piece_edge = OpenCVSolver.apply_canny(piece_img)

offset = OpenCVSolver.find_slider_offset(bg_edge, piece_edge)
print(f"Slider offset: {offset}px")
EOF
```

---

## Steps

1. Identify the CAPTCHA type on the target page:
   - GeeTest: look for `gt_slider_knob` or GeeTest widget JS
   - reCAPTCHA v2: `iframe[src*="recaptcha"]` present
   - reCAPTCHA v3: invisible, fires on form submit / page action
2. Open the page with a `StealthBrowser` or raw Playwright (see `ironcore-stealth-browser`)
3. Instantiate a `MouseEngine` and the appropriate solver
4. Call `solver.solve(page)` — solver handles retries internally
5. Check `result.success` and report

## Prerequisites

```bash
pip install playwright opencv-python-headless numpy pydantic pillow
python3 -m playwright install chromium
```

## Notes
- GeeTest solver uses **OpenCV only** (no API key, no third-party service)
- reCAPTCHA v2 requires a VLM — use `ironcore`'s `VLMBridge` or any LLM with vision
- reCAPTCHA v3 **cannot be "solved"** — only primed via natural-looking behaviour
- `max_attempts=3` is the default retry count for v2 solver
- Combine with `ironcore-stealth-browser` for consistent fingerprint per session
