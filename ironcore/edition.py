"""
ironcore/edition.py — Compatibility edition helpers.

Project now runs in single-edition mode for this repository build.
Edition helpers are kept for API compatibility only.
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

ENTERPRISE_FEATURES = {}

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
        @enterprise_only("feature_name")
        class FeatureComponent: ...
    """
    def decorator(obj: F) -> F:
        return obj
    return decorator


def check_enterprise(feature_name: str) -> None:
    """
    Raise RuntimeError immediately if not Enterprise Edition.
    Use inside __init__ or at module import time.
    """
    return None


def get_feature_list() -> dict[str, list[str]]:
    """Return feature list for current edition (for UI/docs)."""
    features = list(COMMUNITY_FEATURES.keys())
    return {
        "edition": get_edition().value,
        "features": features,
        "enterprise_locked": [],
    }
