"""
ironcore/browser/__init__.py — Browser module public API.

Community Edition (CE): stealth, mouse, session, fingerprint, captcha (basic).
Enterprise Edition (EE): + cloudflare_bypass, datadome_bypass,
                           reddit_bypass, google_form_bypass, bot_evasion.
"""
from __future__ import annotations

from ironcore.edition import is_enterprise, get_edition
import logging

logger = logging.getLogger(__name__)

# ── Core model (single source of truth) ──────────────────────────────────────
from ironcore.browser.stealth import (
    BrowserProfile,
    NavigationResult,
    StealthBrowser,
    stealth_navigate_tool,
    stealth_screenshot_tool,
    get_page_content_tool,
    stealth_click_tool,
    stealth_fill_form_tool,
)

# ── Mouse engine ──────────────────────────────────────────────────────────────
from ironcore.browser.mouse_engine import (
    MouseEngine,
    BezierCurve,
    MousePath,
    generate_mouse_path,
    fitts_time,
)

# ── Captcha solver ────────────────────────────────────────────────────────────
from ironcore.browser.captcha_solver import (
    GeeTestSolverResult,
    ReCaptchaResult,
    TileCoordinateMapper,
    GeeTestSolver,
    ReCaptchaV2Solver,
    ReCaptchaV3Analyzer,
    OpenCVSolver,
)

# ── Fingerprint spoofer Phase 5 ───────────────────────────────────────────────
from ironcore.browser.fingerprint_spoofer import (
    FullFingerprintSpoofer,
    FingerprintVerificationResult,
    DeviceFingerprint,
    DEVICE_FINGERPRINT_LIBRARY,
    get_device_fingerprint,
    get_random_browser_profile,
)

# ── Session manager Phase 6 ───────────────────────────────────────────────────
from ironcore.browser.session_manager import (
    SessionManager,
    ProfilePool,
    ProfileStorage,
    ProfileMetadata,
    ProfileWarmUp,
    StorageStateInfo,
)

# ── Enterprise Edition only — bypass modules ─────────────────────────────────
# These are NOT available in Community Edition.
# Set IRONCORE_EDITION=enterprise to enable.

CloudflareDetector = CloudflareBypass = CloudflareRateLimitHandler = None
DataDomeDetector = DataDomeBypass = None
RedditDetector = RedditBypass = None
GoogleFormDetector = GoogleFormBypass = None
BotDetectionEvasion = ChallengeType = BypassResult = None

if is_enterprise():
    from ironcore.browser.cloudflare_bypass import (
        CloudflareDetector,
        CloudflareBypass,
        CloudflareRateLimitHandler,
    )
    from ironcore.browser.datadome_bypass import (
        DataDomeDetector,
        DataDomeBypass,
    )
    from ironcore.browser.reddit_bypass import (
        RedditDetector,
        RedditBypass,
    )
    from ironcore.browser.google_form_bypass import (
        GoogleFormDetector,
        GoogleFormBypass,
    )
    from ironcore.browser.bot_evasion import (
        BotDetectionEvasion,
        ChallengeType,
        BypassResult,
    )
    logger.info("[Browser] Enterprise Edition — all bypass modules loaded.")
else:
    logger.info(
        "[Browser] Community Edition — bypass modules disabled. "
        "Set IRONCORE_EDITION=enterprise to unlock."
    )

__all__ = [
    # stealth / profiles
    "BrowserProfile", "NavigationResult", "StealthBrowser",
    "stealth_navigate_tool", "stealth_screenshot_tool",
    "get_page_content_tool", "stealth_click_tool", "stealth_fill_form_tool",
    # mouse
    "MouseEngine", "BezierCurve", "MousePath", "generate_mouse_path", "fitts_time",
    # captcha
    "GeeTestSolverResult", "ReCaptchaResult", "TileCoordinateMapper",
    "GeeTestSolver", "ReCaptchaV2Solver", "ReCaptchaV3Analyzer", "OpenCVSolver",
    # fingerprint Phase 5
    "FullFingerprintSpoofer", "FingerprintVerificationResult",
    "DeviceFingerprint", "DEVICE_FINGERPRINT_LIBRARY",
    "get_device_fingerprint", "get_random_browser_profile",
    # session manager Phase 6
    "SessionManager", "ProfilePool", "ProfileStorage",
    "ProfileMetadata", "ProfileWarmUp", "StorageStateInfo",
    # ── Enterprise Edition only (None in CE) ──────────────────────────────────
    "CloudflareDetector", "CloudflareBypass", "CloudflareRateLimitHandler",
    "DataDomeDetector", "DataDomeBypass",
    "RedditDetector", "RedditBypass",
    "GoogleFormDetector", "GoogleFormBypass",
    "BotDetectionEvasion", "ChallengeType", "BypassResult",
]

