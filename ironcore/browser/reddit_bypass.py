"""
ironcore/browser/reddit_bypass.py — Reddit Bot Protection Bypass

Reddit's anti-bot stack (as of 2026):
  - Per-IP rate limiting (HTTP 429 with Retry-After)
  - User-Agent block (rejects Python/requests/curl signatures)
  - Cookie-based session trust (reddit_session, token_v2, loid, session_tracker)
  - Behavioral fingerprinting on reddit.com (scroll cadence, time-on-page)
  - reCAPTCHA v3 (invisible, score-based) on login / signup flows
  - old.reddit.com/.json API: more permissive, usable without JS execution
  - new.reddit.com (shreddit): heavy JS rendering, harder to scrape

Strategy:
  1. RedditDetector — identify rate limit vs. soft block vs. CAPTCHA flow
  2. RedditBypass:
     a. Respect Retry-After on 429
     b. Spoof a realistic Chrome User-Agent + Accept headers
     c. Navigate through old.reddit.com/.json for data access (no JS required)
     d. Inject realistic scroll + dwell time before any interaction
     e. Manage essential Reddit cookies (loid, session) across sessions
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── Lazy imports ─────────────────────────────────────────────────────────────

try:
    from playwright.async_api import Page, Route, Request, Response
except ImportError:
    Page = Any  # type: ignore
    Route = Any  # type: ignore
    Request = Any  # type: ignore
    Response = Any  # type: ignore

try:
    from ironcore.browser.mouse_engine import MouseEngine
except ImportError:
    MouseEngine = None  # type: ignore

# ─── Detection signatures ─────────────────────────────────────────────────────

REDDIT_RATE_LIMIT_BODY = ["you are doing that too much", "try again in"]
REDDIT_BLOCK_BODY = [
    "our cdn was unable to reach our servers",
    "reddit is down",
    "whoa there, pardner",
    "access denied",
    "banned",
]
REDDIT_CAPTCHA_BODY = [
    "g-recaptcha",
    "recaptcha",
    "captcha",
    "i'm not a robot",
]

# Reddit JSON API suffix works on old + new reddit
_REDDIT_JSON_SUFFIX = ".json"

# Realistic Chrome 120 UA — rotated on each session
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
]


# ─── RedditDetector ──────────────────────────────────────────────────────────

class RedditDetector:
    """
    Identify which Reddit bot-protection state the page is in.
    """

    @staticmethod
    async def detect_block_type(page: "Page") -> str:
        """
        Returns: 'rate_limit' | 'soft_block' | 'captcha' | 'none'
        """
        # HTTP 429
        try:
            url = page.url
            if "ratelimited" in url.lower():
                return "rate_limit"
        except Exception:
            pass

        try:
            body = (await page.content()).lower()
        except Exception:
            return "none"

        if any(p in body for p in REDDIT_RATE_LIMIT_BODY):
            return "rate_limit"
        if any(p in body for p in REDDIT_CAPTCHA_BODY):
            return "captcha"
        if any(p in body for p in REDDIT_BLOCK_BODY):
            return "soft_block"

        # New reddit (shreddit) gating check: page has no posts rendered
        try:
            posts = await page.query_selector_all('shreddit-post, [data-testid="post-container"]')
            if not posts and "reddit.com/r/" in page.url:
                # Blank page — likely bot-gated rendering failure
                logger.debug("[Reddit/Detector] Blank subreddit page — possible soft block")
                return "soft_block"
        except Exception:
            pass

        return "none"

    @staticmethod
    def is_reddit_url(url: str) -> bool:
        return bool(re.search(r"(www|old|new)\.reddit\.com", url))

    @staticmethod
    def to_old_reddit(url: str) -> str:
        """Rewrite any reddit.com URL to old.reddit.com equivalent."""
        return re.sub(
            r"https?://(www|new|sh)\.reddit\.com",
            "https://old.reddit.com",
            url,
        )

    @staticmethod
    def to_json_api(url: str) -> str:
        """
        Convert a Reddit page URL to its JSON API equivalent.
        e.g. old.reddit.com/r/python → old.reddit.com/r/python.json
        """
        # Strip query params & fragments
        base = re.sub(r"[?#].*", "", url)
        if not base.endswith(_REDDIT_JSON_SUFFIX):
            base = base.rstrip("/") + _REDDIT_JSON_SUFFIX
        return base


# ─── RedditBypass ─────────────────────────────────────────────────────────────

class RedditBypass:
    """
    Bypass Reddit's bot/rate-limit protections.

    Techniques:
    1. Header spoofing: realistic Chrome Accept/* + sec-ch-ua headers
    2. old.reddit.com routing: more lenient, no JS hydration required
    3. /.json API: scrape structured data without rendering React
    4. Rate-limit respect: parse Retry-After, backoff, re-request
    5. Cookie preservation: persist loid + token_v2 across sessions
    6. Dwell + scroll priming: human-like behavior before interaction
    """

    # Reddit is sensitive to rapid requests — always enforce a floor
    MIN_PAGE_DWELL_SECONDS = 4.0
    MAX_PAGE_DWELL_SECONDS = 12.0
    # Requests per minute floor to stay under Reddit's rate limit
    MIN_INTER_REQUEST_SECONDS = 2.0

    def __init__(self, mouse_engine: Optional["MouseEngine"] = None) -> None:
        self._mouse = mouse_engine
        self._last_request_time: float = 0.0
        self._user_agent: str = random.choice(_USER_AGENTS)

    # ── Header interceptor ────────────────────────────────────────────────────

    async def install_header_interceptor(self, page: "Page") -> None:
        """
        Intercept all requests to reddit.com and inject realistic browser headers.
        Masks Python/Playwright signatures.
        """
        ua = self._user_agent

        async def _handle_route(route: "Route", request: "Request") -> None:
            headers = dict(request.headers)
            headers.update({
                "user-agent": ua,
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "accept-language": "en-US,en;q=0.9",
                "accept-encoding": "gzip, deflate, br",
                "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-site": "none",
                "sec-fetch-user": "?1",
                "upgrade-insecure-requests": "1",
                "dnt": "1",
            })
            await route.continue_(headers=headers)

        try:
            await page.route("**/*reddit.com/**", _handle_route)
            logger.debug("[Reddit/Bypass] Header interceptor installed (UA=%s...)", ua[:40])
        except Exception as exc:
            logger.warning("[Reddit/Bypass] Could not install header interceptor: %s", exc)

    # ── Rate limit ────────────────────────────────────────────────────────────

    async def handle_rate_limit(self, page: "Page", url: str) -> bool:
        """
        Parse Retry-After from response headers or page content and wait.
        Re-navigates to `url` after delay.
        Returns True if page loads cleanly afterwards.
        """
        retry_after = await self._parse_retry_after(page)
        if retry_after <= 0:
            retry_after = 30 + random.uniform(5, 15)  # safe default

        logger.info(
            "[Reddit/Bypass] Rate limited — waiting %.0fs before retry", retry_after
        )
        await asyncio.sleep(retry_after)

        # Rotate UA to further reduce fingerprint match
        self._user_agent = random.choice(_USER_AGENTS)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            block_type = await RedditDetector.detect_block_type(page)
            logger.info("[Reddit/Bypass] After rate-limit wait: block_type=%s", block_type)
            return block_type == "none"
        except Exception as exc:
            logger.error("[Reddit/Bypass] Re-navigation failed: %s", exc)
            return False

    @staticmethod
    async def _parse_retry_after(page: "Page") -> float:
        """Extract Retry-After value (seconds) from page content or headers."""
        try:
            body = (await page.content()).lower()
            # "try again in X minutes" / "try again in X seconds"
            m = re.search(r"try again in (\d+)\s*(minute|second)", body)
            if m:
                val = int(m.group(1))
                if "minute" in m.group(2):
                    val *= 60
                return float(val) + random.uniform(5, 15)
        except Exception:
            pass
        return 0.0

    # ── Soft block recovery ───────────────────────────────────────────────────

    async def recover_soft_block(self, page: "Page", url: str) -> bool:
        """
        Attempt to recover from a soft block by switching to old.reddit.com
        and applying behavioral priming.
        """
        old_url = RedditDetector.to_old_reddit(url)
        logger.info("[Reddit/Bypass] Switching to old.reddit: %s", old_url)

        try:
            await page.goto(old_url, wait_until="domcontentloaded", timeout=30_000)
            await self._dwell_and_scroll(page)
            block_type = await RedditDetector.detect_block_type(page)
            return block_type == "none"
        except Exception as exc:
            logger.error("[Reddit/Bypass] old.reddit navigation failed: %s", exc)
            return False

    # ── JSON API fetch ────────────────────────────────────────────────────────

    async def fetch_json(
        self,
        page: "Page",
        url: str,
        params: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch Reddit's JSON API for a given page URL.
        Converts URL to *.json endpoint and navigates to it.

        Returns parsed JSON dict or None on failure.
        """
        await self._throttle()

        json_url = RedditDetector.to_json_api(RedditDetector.to_old_reddit(url))
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            json_url = f"{json_url}?{qs}"

        logger.debug("[Reddit/Bypass] Fetching JSON API: %s", json_url)

        try:
            response = await page.goto(
                json_url, wait_until="domcontentloaded", timeout=20_000
            )

            # 429 — rate limited
            if response and response.status == 429:
                logger.warning("[Reddit/Bypass] 429 on JSON API")
                await self.handle_rate_limit(page, json_url)
                # Retry once
                response = await page.goto(
                    json_url, wait_until="domcontentloaded", timeout=20_000
                )

            if response and response.status == 200:
                raw = await page.content()
                # Strip HTML wrapper that Playwright adds to plain JSON
                raw = re.sub(r"^.*?<pre[^>]*>", "", raw, flags=re.DOTALL)
                raw = re.sub(r"</pre>.*$", "", raw, flags=re.DOTALL)
                raw = raw.strip()
                return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("[Reddit/Bypass] JSON decode error: %s", exc)
        except Exception as exc:
            logger.error("[Reddit/Bypass] fetch_json error: %s", exc)

        return None

    # ── Fetch subreddit posts ─────────────────────────────────────────────────

    async def fetch_subreddit_posts(
        self,
        page: "Page",
        subreddit: str,
        sort: str = "hot",
        limit: int = 25,
        after: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Fetch posts from a subreddit via the JSON API.

        Args:
            subreddit: Subreddit name (without r/ prefix).
            sort: 'hot' | 'new' | 'top' | 'rising'
            limit: Number of posts (max 100 per Reddit API).
            after: Pagination cursor (fullname of last post).

        Returns:
            List of post data dicts.
        """
        url = f"https://www.reddit.com/r/{subreddit}/{sort}"
        params: Dict[str, str] = {"limit": str(min(limit, 100))}
        if after:
            params["after"] = after

        data = await self.fetch_json(page, url, params)
        if not data:
            return []

        try:
            children = data[0]["data"]["children"] if isinstance(data, list) else data["data"]["children"]
            return [child["data"] for child in children if child.get("kind") == "t3"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("[Reddit/Bypass] Post extraction error: %s", exc)
            return []

    # ── Behavioral priming ────────────────────────────────────────────────────

    async def prime_page(self, page: "Page") -> None:
        """
        Apply human-like behavior before any Reddit interaction:
        dwell time + natural scroll pattern.
        """
        await self._dwell_and_scroll(page)

    async def _dwell_and_scroll(self, page: "Page") -> None:
        """Realistic scroll + dwell to appear human to Reddit's behavioral layer."""
        dwell = random.uniform(self.MIN_PAGE_DWELL_SECONDS, self.MAX_PAGE_DWELL_SECONDS)
        logger.debug("[Reddit/Bypass] Dwelling %.1fs + scrolling", dwell)

        # Phase 1: short wait before scroll
        await asyncio.sleep(random.uniform(1.0, 2.5))

        # Phase 2: gradual scroll down
        try:
            scroll_steps = random.randint(3, 7)
            for _ in range(scroll_steps):
                scroll_by = random.randint(200, 600)
                await page.evaluate(f"window.scrollBy(0, {scroll_by})")
                await asyncio.sleep(random.uniform(0.3, 1.2))
        except Exception:
            pass

        # Phase 3: pause at "bottom"
        remaining = max(0.5, dwell - 2.5)
        await asyncio.sleep(remaining)

    # ── Request throttle ──────────────────────────────────────────────────────

    async def _throttle(self) -> None:
        """Enforce minimum inter-request delay to respect Reddit rate limits."""
        elapsed = time.time() - self._last_request_time
        gap = self.MIN_INTER_REQUEST_SECONDS - elapsed
        if gap > 0:
            jitter = random.uniform(0, 1.0)
            await asyncio.sleep(gap + jitter)
        self._last_request_time = time.time()

    # ── Cookie helpers ────────────────────────────────────────────────────────

    @staticmethod
    async def extract_reddit_cookies(page: "Page") -> List[Dict[str, Any]]:
        """Extract Reddit-specific cookies for session persistence."""
        try:
            ctx = page.context
            cookies = await ctx.cookies(["https://www.reddit.com"])
            important = {"token_v2", "reddit_session", "loid", "session_tracker", "edgebucket"}
            return [c for c in cookies if c.get("name", "") in important]
        except Exception as exc:
            logger.warning("[Reddit/Bypass] Cookie extraction failed: %s", exc)
            return []

    @staticmethod
    async def restore_reddit_cookies(
        page: "Page", cookies: List[Dict[str, Any]]
    ) -> None:
        """Restore previously saved Reddit cookies into the browser context."""
        if not cookies:
            return
        try:
            await page.context.add_cookies(cookies)
            logger.debug("[Reddit/Bypass] Restored %d cookies", len(cookies))
        except Exception as exc:
            logger.warning("[Reddit/Bypass] Cookie restore failed: %s", exc)
