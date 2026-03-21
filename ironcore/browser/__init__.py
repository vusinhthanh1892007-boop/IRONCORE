"""ironcore/browser/__init__.py — Browser module public API (community scope)."""
from __future__ import annotations

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
]

