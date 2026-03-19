"""IronCore V2 — OTA (Over-The-Air) Update Module.

Phase 2 — The Architect (Gemini 3.1)

Exports:
    OTAUpdateManager  — Main update manager class
    UpdateType        — Enum: config | plugin | core
    UpdateResult      — Pydantic result model
"""

from .manager import OTAUpdateManager, UpdateResult, UpdateType

__all__ = ["OTAUpdateManager", "UpdateResult", "UpdateType"]
