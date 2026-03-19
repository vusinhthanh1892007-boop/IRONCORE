"""
ironcore/browser/session_manager.py — Phase 6: Session Manager
Persistent Browser Profiles Database + ProfilePool + Human Warm-Up Simulation.

Architecture:
  ProfileStorage  — JSON file persistence trong ~/.ironcore/profiles/
  ProfileMetadata — Pydantic model cho profile state
  ProfilePool     — N=20 profiles, round-robin rotation + aging score
  SessionManager  — Public interface: get_stealth_browser → return_browser
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ─── Lazy playwright imports (optional runtime dep) ─────────────────────────

try:
    from playwright.async_api import BrowserContext
except ImportError:
    BrowserContext = Any  # type: ignore

try:
    from ironcore.browser.stealth import BrowserProfile, StealthBrowser
except Exception:
    BrowserProfile = Any  # type: ignore
    StealthBrowser = Any  # type: ignore

try:
    from ironcore.browser.fingerprint_spoofer import (
        FullFingerprintSpoofer,
        get_random_browser_profile,
    )
except Exception:
    FullFingerprintSpoofer = None  # type: ignore
    get_random_browser_profile = None  # type: ignore


# ─── Constants ───────────────────────────────────────────────────────────────

PROFILES_DIR = Path.home() / ".ironcore" / "profiles"
POOL_SIZE_DEFAULT = 20
WARMUP_SITES = [
    "https://www.wikipedia.org/",
    "https://www.bbc.com/news",
    "https://www.reddit.com/r/todayilearned/",
    "https://news.ycombinator.com/",
    "https://www.nytimes.com/",
    "https://www.theguardian.com/",
    "https://www.nature.com/",
]

# ─── Pydantic models ──────────────────────────────────────────────────────────


class ProfileMetadata(BaseModel):
    """Persistent metadata stored alongside each profile's storage state."""

    profile_id: str
    name: str
    created_at: float = Field(default_factory=time.time)
    last_used: float = Field(default_factory=time.time)
    usage_count: int = 0
    flag_count: int = 0
    flag_reasons: List[str] = Field(default_factory=list)
    retired: bool = False
    warmed_up: bool = False
    # Fingerprint snapshot
    platform: str = "Win32"
    webgl_vendor: str = ""
    webgl_renderer: str = ""
    locale: str = "en-US"
    timezone: str = "America/New_York"
    user_agent: str = ""

    def age_days(self) -> float:
        return (time.time() - self.created_at) / 86400

    def freshness_score(self) -> float:
        """
        Profile scoring formula:
            score = age_bonus × usage_bonus × trust_factor
        Higher = better (more trusted, well-aged, not flagged).
        """
        age_bonus = math.log1p(self.age_days())          # older = better
        usage_bonus = math.log1p(self.usage_count * 0.5) # some usage = good
        trust_factor = max(0.0, 1.0 - self.flag_count * 0.3)  # each flag -30%
        return age_bonus * usage_bonus * trust_factor


class StorageStateInfo(BaseModel):
    """Thin wrapper around Playwright storage state path info."""

    profile_id: str
    storage_path: str          # absolute path to storage.json
    metadata_path: str         # absolute path to metadata.json
    exists: bool = False


# ─── 6.1 ProfileStorage ──────────────────────────────────────────────────────

class ProfileStorage:
    """
    Handles persistent I/O for browser profiles.

    Layout:
        ~/.ironcore/profiles/<profile_id>/
            storage.json      ← Playwright storageState (cookies, localStorage)
            metadata.json     ← ProfileMetadata
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = base_dir or PROFILES_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _profile_dir(self, profile_id: str) -> Path:
        d = self.base_dir / profile_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _storage_path(self, profile_id: str) -> Path:
        return self._profile_dir(profile_id) / "storage.json"

    def _metadata_path(self, profile_id: str) -> Path:
        return self._profile_dir(profile_id) / "metadata.json"

    # ── Write ────────────────────────────────────────────────────────────────

    async def save_profile(
        self,
        context: "BrowserContext",
        metadata: ProfileMetadata,
    ) -> None:
        """
        Persist browser storage state + profile metadata to disk.
        Playwright's context.storage_state() captures cookies, localStorage, sessionStorage.
        """
        storage_path = self._storage_path(metadata.profile_id)
        try:
            await context.storage_state(path=str(storage_path))
            logger.info(
                "[Ghost/SessionManager] Saved storage state → %s", storage_path
            )
        except Exception as exc:
            logger.warning(
                "[Ghost/SessionManager] save_profile storage_state failed: %s", exc
            )

        await self._write_metadata(metadata)

    async def _write_metadata(self, metadata: ProfileMetadata) -> None:
        meta_path = self._metadata_path(metadata.profile_id)
        loop = asyncio.get_running_loop()
        data = metadata.model_dump()
        await loop.run_in_executor(
            None,
            lambda: meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8"),
        )
        logger.debug("[Ghost/SessionManager] Wrote metadata → %s", meta_path)

    # ── Read ─────────────────────────────────────────────────────────────────

    async def load_storage_state(self, profile_id: str) -> Optional[str]:
        """
        Returns path to storage.json if it exists, else None.
        Pass this path to BrowserContext 'storage_state' option.
        """
        p = self._storage_path(profile_id)
        return str(p) if p.exists() else None

    async def load_metadata(self, profile_id: str) -> Optional[ProfileMetadata]:
        p = self._metadata_path(profile_id)
        if not p.exists():
            return None
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(
            None, lambda: p.read_text(encoding="utf-8")
        )
        return ProfileMetadata.model_validate(json.loads(raw))

    async def update_metadata(
        self,
        profile_id: str,
        **fields: Any,
    ) -> Optional[ProfileMetadata]:
        meta = await self.load_metadata(profile_id)
        if meta is None:
            return None
        updated = meta.model_copy(update=fields)
        await self._write_metadata(updated)
        return updated

    async def delete_profile(self, profile_id: str) -> None:
        import shutil
        d = self.base_dir / profile_id
        if d.exists():
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: shutil.rmtree(str(d)))
            logger.info("[Ghost/SessionManager] Deleted profile %s", profile_id)

    async def list_profiles(self) -> List[ProfileMetadata]:
        """Return all non-retired profiles sorted by freshness score descending."""
        profiles: List[ProfileMetadata] = []
        loop = asyncio.get_running_loop()

        def _scan() -> List[Path]:
            return [
                p for p in self.base_dir.iterdir()
                if p.is_dir() and (p / "metadata.json").exists()
            ]

        dirs = await loop.run_in_executor(None, _scan)
        for d in dirs:
            meta = await self.load_metadata(d.name)
            if meta and not meta.retired:
                profiles.append(meta)

        profiles.sort(key=lambda m: m.freshness_score(), reverse=True)
        return profiles


# ─── 6.2 ProfilePool ─────────────────────────────────────────────────────────

class ProfilePool:
    """
    Manages a rotating pool of browser profiles.

    Strategy:
    - Maintain up to `size` active profiles.
    - Selection: weighted random by freshness_score (higher = preferred).
    - On flag: decrement trust, retire after 3 flags.
    - Auto-replenish: when pool drops below min_size, create fresh profiles.
    """

    def __init__(
        self,
        storage: Optional[ProfileStorage] = None,
        size: int = POOL_SIZE_DEFAULT,
        min_size: int = 5,
    ) -> None:
        self.storage = storage or ProfileStorage()
        self.size = size
        self.min_size = min_size
        self._pool: List[ProfileMetadata] = []     # in-memory cache
        self._lock = asyncio.Lock()
        self._rr_index: int = 0                    # round-robin cursor

    async def initialize(self) -> None:
        """Load existing profiles from disk, create fresh ones if needed."""
        async with self._lock:
            self._pool = await self.storage.list_profiles()
            shortage = max(0, self.min_size - len(self._pool))
            for _ in range(shortage):
                meta = await self.create_fresh_profile()
                self._pool.append(meta)
            logger.info(
                "[Ghost/ProfilePool] Initialized: %d profiles (created %d fresh)",
                len(self._pool), shortage
            )

    # ── Public API ───────────────────────────────────────────────────────────

    async def get_next_profile(self) -> "BrowserProfile":
        """
        Return the next profile using weighted-random selection by freshness_score.
        Falls back to round-robin if all scores are 0.
        """
        async with self._lock:
            if not self._pool:
                meta = await self.create_fresh_profile()
                self._pool.append(meta)

            scores = [m.freshness_score() for m in self._pool]
            total = sum(scores)

            if total > 0:
                # Weighted random pick
                r = random.uniform(0, total)
                cumsum = 0.0
                chosen = self._pool[-1]
                for i, meta in enumerate(self._pool):
                    cumsum += scores[i]
                    if r <= cumsum:
                        chosen = meta
                        break
            else:
                # Fallback: pure round-robin
                self._rr_index = (self._rr_index + 1) % len(self._pool)
                chosen = self._pool[self._rr_index]

            # Update last_used
            chosen = await self.storage.update_metadata(
                chosen.profile_id,
                last_used=time.time(),
                usage_count=chosen.usage_count + 1,
            ) or chosen
            self._sync_pool_entry(chosen)

        logger.info(
            "[Ghost/ProfilePool] get_next_profile → %s (score=%.2f, uses=%d)",
            chosen.profile_id, chosen.freshness_score(), chosen.usage_count
        )
        return self._meta_to_browser_profile(chosen)

    async def mark_flagged(self, profile_id: str, reason: str) -> None:
        """Mark a profile as having been detected by bot protection."""
        meta = await self.storage.load_metadata(profile_id)
        if meta is None:
            return
        new_flags = meta.flag_count + 1
        new_reasons = meta.flag_reasons + [f"{time.strftime('%Y-%m-%dT%H:%M:%S')}: {reason}"]
        should_retire = new_flags >= 3

        updated = await self.storage.update_metadata(
            profile_id,
            flag_count=new_flags,
            flag_reasons=new_reasons,
            retired=should_retire,
        )
        if should_retire and updated:
            await self.retire_profile(profile_id)
            logger.warning(
                "[Ghost/ProfilePool] Profile %s RETIRED after %d flags. Last: %s",
                profile_id, new_flags, reason
            )
        else:
            logger.warning(
                "[Ghost/ProfilePool] Profile %s flagged (%d/3): %s",
                profile_id, new_flags, reason
            )
        # Replenish pool if short
        await self._replenish_if_needed()

    async def retire_profile(self, profile_id: str) -> None:
        """Remove a profile from the active pool (soft retire, keeps disk data)."""
        async with self._lock:
            self._pool = [m for m in self._pool if m.profile_id != profile_id]
        await self.storage.update_metadata(profile_id, retired=True)
        logger.info("[Ghost/ProfilePool] Retired profile %s", profile_id)

    async def create_fresh_profile(self) -> ProfileMetadata:
        """
        Create a new profile with random fingerprint from DEVICE_FINGERPRINT_LIBRARY.
        Returns ProfileMetadata (saved to disk). Does NOT warm up.
        """
        profile_id = f"ghost-{uuid.uuid4().hex[:12]}"
        seed = random.randint(0, 999_999)

        if get_random_browser_profile is not None:
            bp: "BrowserProfile" = get_random_browser_profile(profile_id, seed)
        else:
            # Minimal fallback when fingerprint_spoofer not importable
            from ironcore.browser.stealth import BrowserProfile as _BP
            bp = _BP(
                profile_id=profile_id,
                name=f"Fresh Profile {seed}",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport=(1920, 1080),
                locale="en-US",
                timezone="America/New_York",
                platform="Win32",
                webgl_vendor="Google Inc. (NVIDIA)",
                webgl_renderer="ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11)",
                canvas_noise_seed=seed,
            )

        meta = ProfileMetadata(
            profile_id=profile_id,
            name=bp.name,
            platform=bp.platform,
            webgl_vendor=bp.webgl_vendor,
            webgl_renderer=bp.webgl_renderer,
            locale=bp.locale,
            timezone=bp.timezone,
            user_agent=bp.user_agent,
        )
        await self.storage._write_metadata(meta)
        logger.info(
            "[Ghost/ProfilePool] Created fresh profile %s (%s)",
            profile_id, bp.name
        )
        return meta

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _sync_pool_entry(self, updated: ProfileMetadata) -> None:
        """Replace in-memory pool entry with updated version."""
        for i, m in enumerate(self._pool):
            if m.profile_id == updated.profile_id:
                self._pool[i] = updated
                break

    def _meta_to_browser_profile(self, meta: ProfileMetadata) -> "BrowserProfile":
        """Convert ProfileMetadata → BrowserProfile for use with StealthBrowser."""
        if get_random_browser_profile is not None:
            seed = abs(hash(meta.profile_id)) % 6
            return get_random_browser_profile(meta.profile_id, seed)

        from ironcore.browser.stealth import BrowserProfile as _BP
        return _BP(
            profile_id=meta.profile_id,
            name=meta.name,
            user_agent=meta.user_agent or "Mozilla/5.0",
            viewport=(1920, 1080),
            locale=meta.locale,
            timezone=meta.timezone,
            platform=meta.platform,
            webgl_vendor=meta.webgl_vendor,
            webgl_renderer=meta.webgl_renderer,
            canvas_noise_seed=abs(hash(meta.profile_id)) % 999999,
        )

    async def _replenish_if_needed(self) -> None:
        async with self._lock:
            active_count = len([m for m in self._pool if not m.retired])
            shortage = self.min_size - active_count
        if shortage > 0:
            for _ in range(shortage):
                meta = await self.create_fresh_profile()
                async with self._lock:
                    self._pool.append(meta)
            logger.info(
                "[Ghost/ProfilePool] Replenished %d profiles", shortage
            )

    async def pool_status(self) -> Dict[str, Any]:
        """Return diagnostic snapshot of pool state."""
        async with self._lock:
            return {
                "total": len(self._pool),
                "retired": sum(1 for m in self._pool if m.retired),
                "flagged": sum(1 for m in self._pool if m.flag_count > 0),
                "warmed_up": sum(1 for m in self._pool if m.warmed_up),
                "profiles": [
                    {
                        "id": m.profile_id,
                        "name": m.name,
                        "score": round(m.freshness_score(), 3),
                        "uses": m.usage_count,
                        "flags": m.flag_count,
                        "age_days": round(m.age_days(), 2),
                        "warmed": m.warmed_up,
                    }
                    for m in self._pool
                ],
            }


# ─── 6.3 Human Browsing Warm-Up ──────────────────────────────────────────────

class ProfileWarmUp:
    """
    Simulate a real user browsing session to build genuine history.

    Strategy:
    - Visit 3-5 random harmless websites.
    - Spend realistic time (gaussian(60s, 20s)) on each.
    - Scroll page randomly with MouseEngine.
    - This makes Playwright cookies/localStorage look genuine.
    """

    SCROLL_STEPS = (3, 8)       # min/max scroll actions per page
    READING_PAUSE_MU = 3.0      # seconds — mean pause reading per scroll
    READING_PAUSE_SIGMA = 1.0

    @staticmethod
    async def warm_up_profile(browser: "StealthBrowser") -> None:
        """
        Execute warm-up routine on a StealthBrowser instance.
        Visits 3-5 harmless sites and simulates genuine browsing.
        """
        sites = random.sample(WARMUP_SITES, k=random.randint(3, 5))
        logger.info(
            "[Ghost/WarmUp] Starting warm-up on %d sites", len(sites)
        )

        for i, url in enumerate(sites):
            try:
                await ProfileWarmUp._visit_site(browser, url, site_index=i + 1)
            except Exception as exc:
                logger.warning(
                    "[Ghost/WarmUp] Failed to warm up on %s: %s", url, exc
                )

        logger.info("[Ghost/WarmUp] Warm-up complete — %d sites visited", len(sites))

    @staticmethod
    async def _visit_site(
        browser: "StealthBrowser",
        url: str,
        site_index: int,
    ) -> None:
        """Navigate to one site, scroll it, and wait realistic time."""
        page = browser._page
        if page is None:
            return

        # Navigate
        logger.debug("[Ghost/WarmUp] [%d] Visiting %s", site_index, url)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        except Exception as exc:
            logger.debug("[Ghost/WarmUp] navigate error: %s", exc)
            return

        # Initial reading pause (simulates user reading headline)
        initial_pause = max(1.0, random.gauss(4.0, 1.5))
        await asyncio.sleep(initial_pause)

        # Scroll page naturally
        num_scrolls = random.randint(*ProfileWarmUp.SCROLL_STEPS)
        viewport_height = 768
        try:
            dims = await page.evaluate(
                "() => ({height: document.body.scrollHeight, vh: window.innerHeight})"
            )
            viewport_height = dims.get("vh", 768)
            doc_height = dims.get("height", 3000)
        except Exception:
            doc_height = 3000

        current_scroll = 0
        scroll_unit = viewport_height * random.uniform(0.6, 0.9)

        for _ in range(num_scrolls):
            # Smooth scroll down
            target_scroll = min(doc_height - viewport_height, current_scroll + scroll_unit)
            try:
                await page.evaluate(
                    f"window.scrollTo({{top: {target_scroll:.0f}, behavior: 'smooth'}})"
                )
            except Exception:
                pass
            current_scroll = target_scroll

            # Reading pause between scrolls
            pause = max(0.5, random.gauss(
                ProfileWarmUp.READING_PAUSE_MU,
                ProfileWarmUp.READING_PAUSE_SIGMA,
            ))
            await asyncio.sleep(pause)

        # Final dwell time (simulate user finishing reading article)
        final_dwell = max(2.0, random.gauss(8.0, 3.0))
        await asyncio.sleep(final_dwell)

        total_time = initial_pause + (num_scrolls * ProfileWarmUp.READING_PAUSE_MU) + final_dwell
        logger.debug(
            "[Ghost/WarmUp] [%d] Done %-50s scrolls=%d dwell≈%.0fs",
            site_index, url, num_scrolls, total_time
        )


# ─── 6.4 SessionManager ──────────────────────────────────────────────────────

_TASK_PROFILE_HINTS: Dict[str, str] = {
    "scraping": "high_usage",
    "captcha": "fresh",
    "checkout": "aged",
    "default": "any",
}


class SessionManager:
    """
    Phase 6 public interface — the single entry point for browser session management.

    Usage:
        manager = SessionManager()
        await manager.initialize()

        browser = await manager.get_stealth_browser("checkout")
        # ... use browser ...
        await manager.return_browser(browser, success=True)
    """

    def __init__(
        self,
        pool_size: int = POOL_SIZE_DEFAULT,
        profiles_dir: Optional[Path] = None,
        warmup_new_profiles: bool = True,
    ) -> None:
        self.pool = ProfilePool(
            storage=ProfileStorage(profiles_dir),
            size=pool_size,
        )
        self.warmup_new_profiles = warmup_new_profiles
        self._active_browsers: Dict[str, "StealthBrowser"] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Must be called before using get_stealth_browser."""
        if self._initialized:
            return
        await self.pool.initialize()
        self._initialized = True
        logger.info(
            "[Ghost/SessionManager] Ready — pool_size=%d warmup=%s",
            self.pool.size, self.warmup_new_profiles
        )

    async def get_stealth_browser(
        self,
        task_type: str = "default",
    ) -> "StealthBrowser":
        """
        Select a profile appropriate for task_type, launch a StealthBrowser,
        warm up if the profile is brand-new, return a ready-to-use browser.

        Args:
            task_type: Hint for profile selection.
                       One of: 'scraping', 'captcha', 'checkout', 'default'.
        """
        if not self._initialized:
            await self.initialize()

        profile = await self.pool.get_next_profile()
        logger.info(
            "[Ghost/SessionManager] Launching browser: profile=%s task=%s",
            profile.profile_id, task_type
        )

        browser = await self._launch_browser(profile)

        # Warm up brand-new profiles
        meta = await self.pool.storage.load_metadata(profile.profile_id)
        if meta and not meta.warmed_up and self.warmup_new_profiles:
            logger.info(
                "[Ghost/SessionManager] Warming up new profile %s", profile.profile_id
            )
            try:
                await ProfileWarmUp.warm_up_profile(browser)
                await self.pool.storage.update_metadata(
                    profile.profile_id, warmed_up=True
                )
            except Exception as exc:
                logger.warning(
                    "[Ghost/SessionManager] Warm-up failed: %s", exc
                )

        self._active_browsers[profile.profile_id] = browser
        return browser

    async def return_browser(
        self,
        browser: "StealthBrowser",
        success: bool,
        failure_reason: Optional[str] = None,
    ) -> None:
        """
        Return a browser to the pool after use.
        - success=True: save storage state (preserve cookies, etc.)
        - success=False: flag profile with reason.
        """
        profile_id = getattr(browser, "_profile_id", None)
        if profile_id is None and hasattr(browser, "profile"):
            profile_id = getattr(browser.profile, "profile_id", None)

        if profile_id and success:
            # Persist cookies/localStorage for next use
            if hasattr(browser, "_context") and browser._context is not None:
                meta = await self.pool.storage.load_metadata(profile_id)
                if meta:
                    try:
                        await self.pool.storage.save_profile(browser._context, meta)
                        logger.info(
                            "[Ghost/SessionManager] Saved storage state for %s", profile_id
                        )
                    except Exception as exc:
                        logger.warning(
                            "[Ghost/SessionManager] Could not save storage state: %s", exc
                        )
        elif profile_id and not success:
            reason = failure_reason or "unknown_failure"
            await self.pool.mark_flagged(profile_id, reason)

        # Close browser
        try:
            await browser.close()
        except Exception as exc:
            logger.debug("[Ghost/SessionManager] browser.close() error: %s", exc)

        # Remove from active map
        if profile_id:
            self._active_browsers.pop(profile_id, None)

        logger.info(
            "[Ghost/SessionManager] Browser returned: profile=%s success=%s",
            profile_id, success
        )

    async def pool_status(self) -> Dict[str, Any]:
        """Diagnostic: return pool snapshot."""
        return await self.pool.pool_status()

    async def shutdown(self) -> None:
        """Close all active browsers gracefully."""
        logger.info(
            "[Ghost/SessionManager] Shutdown: closing %d active browsers",
            len(self._active_browsers)
        )
        for bid, browser in list(self._active_browsers.items()):
            try:
                await browser.close()
            except Exception:
                pass
        self._active_browsers.clear()

    # ── Internal ─────────────────────────────────────────────────────────────

    @staticmethod
    async def _launch_browser(profile: "BrowserProfile") -> "StealthBrowser":
        """Initialize and launch a StealthBrowser with the given profile."""
        from ironcore.browser.stealth import StealthBrowser
        browser = StealthBrowser(profile)
        await browser.launch()
        return browser
