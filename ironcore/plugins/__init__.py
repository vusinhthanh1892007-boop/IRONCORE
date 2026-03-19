"""
IronCore V2: Plugin System
============================
Phase 1 — The Architect (Gemini 3.1)

Package exports cho plugin subsystem.
Public API dùng bởi các agents và API server.
"""

from .manifest import (
    ManifestValidationError,
    PluginError,
    PluginInfo,
    PluginInstallError,
    PluginManifest,
    PluginNotFoundError,
    PluginPermission,
    PluginSecurityError,
    PluginSource,
    PluginStatus,
    ToolSpec,
)
from .loader import PluginLoader
from .registry import PluginRegistry
from .marketplace import PluginMarketplace

__all__ = [
    # Exceptions
    "PluginError",
    "ManifestValidationError",
    "PluginSecurityError",
    "PluginInstallError",
    "PluginNotFoundError",
    # Models
    "PluginManifest",
    "PluginInfo",
    "PluginPermission",
    "PluginStatus",
    "PluginSource",
    "ToolSpec",
    # Classes
    "PluginLoader",
    "PluginRegistry",
    "PluginMarketplace",
]
