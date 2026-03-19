"""
IronCore V2: OTA API Routes
=============================
Phase 2 — The Architect (Gemini 3.1)

Exposes:
  GET  /api/ota/status                    — current version + available updates
  POST /api/ota/check                     — force refresh of available updates
  POST /api/ota/apply/config              — hot config reload
  POST /api/ota/apply/plugin/{plugin_id}  — warm plugin update
  POST /api/ota/apply/core                — full core update (admin only)
  POST /api/ota/rollback/{timestamp}      — rollback to backup (admin only)
  GET  /api/ota/backups                   — list available rollback points

All write endpoints require a valid admin API key (X-IronCore-API-Key header).
Read-only endpoints (status, check) require a valid user-level key.

Author: The Architect (IronCore V2) — Gemini 3.1
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ironcore.api.auth import AuthenticatedPrincipal
from ironcore.ota.manager import OTAUpdateManager, UpdateResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ota", tags=["ota"])


# ─── Request models ─────────────────────────────────────────────────────────

class ConfigUpdateRequest(BaseModel):
    """Body for hot config update."""
    config: Dict[str, str] = Field(
        ...,
        description="Key-value pairs to set in os.environ. Keys must be UPPER_CASE.",
        example={"IRONCORE_LOG_LEVEL": "DEBUG", "IRONCORE_CACHE_ENABLED": "true"},
    )


class CoreUpdateRequest(BaseModel):
    """Body for core update (target_version reserved for future git-tag targeting)."""
    target_version: str = Field(
        default="latest",
        description="Reserved: always pulls HEAD of current branch in V2.",
    )


# ─── Dependency helpers ─────────────────────────────────────────────────────

def _get_ota_manager(request: Request) -> OTAUpdateManager:
    manager: OTAUpdateManager = getattr(request.app.state, "ota_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=503,
            detail="OTA manager not initialised. Ensure IRONCORE_OTA_ENABLED=true.",
        )
    return manager


def _get_plugin_registry(request: Request) -> Any:
    """Return PluginRegistry from app state (set during lifespan in server.py)."""
    return getattr(request.app.state, "plugin_registry", None)


def _require_user(request: Request) -> AuthenticatedPrincipal:
    api_key = request.headers.get("X-IronCore-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-IronCore-API-Key header.")
    principal = request.app.state.auth.authenticate(
        raw_api_key=api_key, require_admin=False
    )
    if principal is None:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return principal


def _require_admin(request: Request) -> AuthenticatedPrincipal:
    api_key = request.headers.get("X-IronCore-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-IronCore-API-Key header.")
    principal = request.app.state.auth.authenticate(
        raw_api_key=api_key, require_admin=True
    )
    if principal is None:
        raise HTTPException(
            status_code=403, detail="Admin API key required for this operation."
        )
    return principal


# ─── Routes ─────────────────────────────────────────────────────────────────

@router.get("/status")
async def ota_status(
    request: Request,
    _: AuthenticatedPrincipal = Depends(_require_user),
) -> Dict[str, Any]:
    """Return the current IronCore version and any pending upstream updates."""
    manager = _get_ota_manager(request)
    current = await manager.get_current_version()
    available = await manager.check_updates()
    return {
        "current_version": current,
        "available_updates": available,
        "update_pending": len(available) > 0,
    }


@router.post("/check")
async def ota_check(
    request: Request,
    _: AuthenticatedPrincipal = Depends(_require_user),
) -> Dict[str, Any]:
    """Force a ``git fetch`` and return pending update info."""
    manager = _get_ota_manager(request)
    available = await manager.check_updates()
    return {
        "available_updates": available,
        "update_pending": len(available) > 0,
    }


@router.post("/apply/config", response_model=UpdateResult)
async def apply_config_update(
    request: Request,
    body: ConfigUpdateRequest,
    _: AuthenticatedPrincipal = Depends(_require_admin),
) -> UpdateResult:
    """Hot-apply environment-variable changes — no restart required.

    All keys are validated before any change is applied.
    """
    manager = _get_ota_manager(request)
    result = await manager.update_config(body.config)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    return result


@router.post("/apply/plugin/{plugin_id}", response_model=UpdateResult)
async def apply_plugin_update(
    request: Request,
    plugin_id: str,
    _: AuthenticatedPrincipal = Depends(_require_admin),
) -> UpdateResult:
    """Pull and hot-reload a specific plugin.

    Requires the plugin to have a git remote configured in its directory.
    Auto-rolls back if the hot-reload fails.
    """
    manager = _get_ota_manager(request)
    plugin_registry = _get_plugin_registry(request)
    if plugin_registry is None:
        raise HTTPException(
            status_code=503, detail="PluginRegistry not initialised."
        )
    result = await manager.update_plugin(plugin_id, plugin_registry)
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)
    return result


@router.post("/apply/core", response_model=UpdateResult)
async def apply_core_update(
    request: Request,
    body: CoreUpdateRequest,
    _: AuthenticatedPrincipal = Depends(_require_admin),
) -> UpdateResult:
    """Perform a full core update via git pull, then trigger a graceful restart.

    The service will restart ~2 s after this response is sent.
    Monitor ``GET /api/ota/status`` once the service comes back up to confirm
    the new version.  If the pull fails the HEAD is immediately reverted.
    """
    manager = _get_ota_manager(request)
    result = await manager.update_core(target_version=body.target_version)
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)
    return result


@router.post("/rollback/{backup_timestamp}", response_model=UpdateResult)
async def rollback_core(
    request: Request,
    backup_timestamp: str,
    _: AuthenticatedPrincipal = Depends(_require_admin),
) -> UpdateResult:
    """Roll back the core to a previously recorded git commit.

    ``backup_timestamp`` must be in ``YYYYMMDD_HHMMSS`` format (e.g.
    ``20260311_142530``).  Available timestamps are listed at
    ``GET /api/ota/backups``.
    """
    manager = _get_ota_manager(request)
    result = await manager.rollback(backup_timestamp)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    return result


@router.get("/backups")
async def list_backups(
    request: Request,
    _: AuthenticatedPrincipal = Depends(_require_admin),
) -> Dict[str, Any]:
    """List all available core rollback backup timestamps."""
    manager = _get_ota_manager(request)
    backups = await manager.list_backups()
    return {"backups": backups, "count": len(backups)}
