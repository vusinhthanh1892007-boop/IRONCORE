"""
ironcore/edition.py — Edition control for IronCore CE vs EE.

Community Edition (CE):  Free, open source, no bypass modules.
Enterprise Edition (EE): Full features, requires license key, includes all bypass modules.

Set via environment variable:
  IRONCORE_EDITION=community   → CE (default)
  IRONCORE_EDITION=enterprise  → EE (requires IRONCORE_LICENSE_KEY)
"""
from __future__ import annotations

import os
import logging
from enum import Enum
from typing import Callable, TypeVar, Any

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class Edition(str, Enum):
    COMMUNITY = "community"
    ENTERPRISE = "enterprise"


def get_edition() -> Edition:
    """Return the current edition from environment variable."""
    raw = os.getenv("IRONCORE_EDITION", "community").strip().lower()
    try:
        return Edition(raw)
    except ValueError:
        logger.warning(
            "[Edition] Unknown IRONCORE_EDITION=%r — defaulting to community.", raw
        )
        return Edition.COMMUNITY


def is_enterprise() -> bool:
    """True if running Enterprise Edition."""
    return get_edition() == Edition.ENTERPRISE


def is_community() -> bool:
    """True if running Community Edition."""
    return get_edition() == Edition.COMMUNITY


# ── Feature flags ─────────────────────────────────────────────────────────────

ENTERPRISE_FEATURES = {
    "cloudflare_bypass":   "Bypass Cloudflare anti-bot protection",
    "datadome_bypass":     "Bypass DataDome bot detection",
    "reddit_bypass":       "Reddit-specific bot evasion",
    "google_form_bypass":  "Google Form automation bypass",
    "full_bot_evasion":    "Full bot evasion orchestration",
}

COMMUNITY_FEATURES = {
    "stealth_browser":     "Stealth browser with human-like behavior",
    "mouse_engine":        "Human-like mouse movement simulation",
    "session_manager":     "Browser session pool management",
    "fingerprint_spoofer": "Browser fingerprint randomization (privacy)",
    "captcha_solver":      "Basic CAPTCHA assistance (accessibility)",
    "ai_chat":             "Multi-agent AI chat",
    "graph_rag":           "GraphRAG memory",
    "lsp_bridge":          "LSP code intelligence bridge",
    "vlm":                 "Visual Language Model integration",
    "token_optimizer":     "Token cost optimizer",
    "plugin_system":       "Plugin install/uninstall",
    "web_ui":              "Web chat interface",
    "channel_bots":        "Telegram & Discord bots",
    "scheduler":           "APScheduler cron jobs",
    "webhooks":            "Inbound webhook listener",
    "mcp_server":          "MCP Protocol server",
}


def enterprise_only(feature_name: str) -> Callable[[F], F]:
    """
    Decorator: raise RuntimeError if function is called in Community Edition.

    Usage:
        @enterprise_only("datadome_bypass")
        class DataDomeBypass: ...
    """
    def decorator(obj: F) -> F:
        if not is_enterprise():
            # Replace class/function with a stub that raises on instantiation/call
            import functools

            @functools.wraps(obj)  # type: ignore[arg-type]
            def stub(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError(
                    f"[IronCore CE] '{feature_name}' is an Enterprise Edition feature.\n"
                    f"  Set IRONCORE_EDITION=enterprise to unlock.\n"
                    f"  Description: {ENTERPRISE_FEATURES.get(feature_name, '')}"
                )
            return stub  # type: ignore[return-value]
        return obj
    return decorator


def check_enterprise(feature_name: str) -> None:
    """
    Raise RuntimeError immediately if not Enterprise Edition.
    Use inside __init__ or at module import time.
    """
    if not is_enterprise():
        raise RuntimeError(
            f"[IronCore CE] '{feature_name}' requires Enterprise Edition.\n"
            f"  Set IRONCORE_EDITION=enterprise to unlock.\n"
            f"  Description: {ENTERPRISE_FEATURES.get(feature_name, '')}"
        )


def get_feature_list() -> dict[str, list[str]]:
    """Return feature list for current edition (for UI/docs)."""
    features = list(COMMUNITY_FEATURES.keys())
    if is_enterprise():
        features += list(ENTERPRISE_FEATURES.keys())
    return {
        "edition": get_edition().value,
        "features": features,
        "enterprise_locked": [] if is_enterprise() else list(ENTERPRISE_FEATURES.keys()),
    }
