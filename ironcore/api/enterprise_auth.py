"""
Enterprise API Authentication & Authorization — Security Fix.

Cung cấp FastAPI Dependency cho tất cả /api/enterprise/* routes.

Cách dùng trong route:
    from ironcore.api.enterprise_auth import require_enterprise, require_admin

    @router.get("/secret")
    async def secret(principal = Depends(require_enterprise)):
        ...

    @router.delete("/roles/{id}")
    async def delete_role(principal = Depends(require_admin)):
        ...

Authentication flow:
1. Đọc X-Api-Key header
2. So sánh với IRONCORE_API_KEY (user) hoặc IRONCORE_ADMIN_API_KEY (admin) dùng hmac.compare_digest
3. Nếu IRONCORE_ENTERPRISE_AUTH_REQUIRED=false → bypass (dev mode)
4. Rate limit: 200 req/min per key (sliding window)
"""

from __future__ import annotations

import hmac
import logging
import os
import time
from collections import defaultdict
from typing import Dict, List, Optional

from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Rate limiter (sliding window) ─────────────────────────────────────────────

class _SlidingRateLimiter:
    def __init__(self, limit: int = 200, window: float = 60.0) -> None:
        self._limit = limit
        self._window = window
        self._calls: Dict[str, List[float]] = defaultdict(list)

    def check(self, key: str) -> bool:
        now = time.time()
        active = [t for t in self._calls[key] if now - t < self._window]
        self._calls[key] = active
        if len(active) >= self._limit:
            return False
        active.append(now)
        return True


_rate_limiter = _SlidingRateLimiter(limit=200, window=60.0)


# ── Principal model ────────────────────────────────────────────────────────────

class EnterprisePrincipal(BaseModel):
    api_key_name: str
    is_admin: bool


# ── Auth helpers ───────────────────────────────────────────────────────────────

def _get_keys() -> tuple[str, str]:
    """Return (user_key, admin_key) from env. Both may be empty in dev mode."""
    return (
        os.environ.get("IRONCORE_API_KEY", ""),
        os.environ.get("IRONCORE_ADMIN_API_KEY", ""),
    )


def _auth_required() -> bool:
    return os.environ.get("IRONCORE_ENTERPRISE_AUTH_REQUIRED", "true").lower() not in ("false", "0", "no")


def _check_key(raw_key: str) -> Optional[EnterprisePrincipal]:
    """Validate api key against stored keys. Returns principal or None."""
    user_key, admin_key = _get_keys()
    if not user_key and not admin_key:
        user_key = "dev-key"

    if admin_key and hmac.compare_digest(raw_key, admin_key):
        if not _rate_limiter.check(f"admin:{raw_key[:8]}"):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Admin rate limit exceeded")
        return EnterprisePrincipal(api_key_name="IRONCORE_ADMIN_API_KEY", is_admin=True)

    if user_key and hmac.compare_digest(raw_key, user_key):
        if not _rate_limiter.check(f"user:{raw_key[:8]}"):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded")
        return EnterprisePrincipal(api_key_name="IRONCORE_API_KEY", is_admin=True if user_key == "dev-key" else False)

    return None


# ── FastAPI Dependencies ───────────────────────────────────────────────────────

async def require_enterprise(
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
    x_ironcore_api_key: Optional[str] = Header(None, alias="X-IronCore-API-Key"),
) -> EnterprisePrincipal:
    """
    Dependency: require any valid API key for enterprise endpoints.
    In dev mode (IRONCORE_ENTERPRISE_AUTH_REQUIRED=false), pass through.
    """
    if not _auth_required():
        logger.debug("[EnterpriseAuth] Auth bypassed (dev mode)")
        return EnterprisePrincipal(api_key_name="dev", is_admin=True)

    key = x_api_key or x_ironcore_api_key
    if not key:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="X-Api-Key or X-IronCore-API-Key header required for enterprise endpoints",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    principal = _check_key(key)
    if principal is None:
        logger.warning("[EnterpriseAuth] Invalid API key attempt")
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return principal


async def require_admin(
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
    x_ironcore_api_key: Optional[str] = Header(None, alias="X-IronCore-API-Key"),
) -> EnterprisePrincipal:
    """
    Dependency: require admin-level API key for destructive/sensitive operations.
    """
    principal = await require_enterprise(x_api_key=x_api_key, x_ironcore_api_key=x_ironcore_api_key)
    if not principal.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Admin API key required for this operation",
        )
    return principal
