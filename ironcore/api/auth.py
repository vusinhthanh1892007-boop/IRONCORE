"""API-key authentication and in-memory rate limiting for IronCore."""

from __future__ import annotations

import hmac
import time
from collections import defaultdict
from typing import DefaultDict, Dict, List, Optional

from pydantic import BaseModel

from ironcore.security.secrets_vault import SecretsVault


class AuthenticatedPrincipal(BaseModel):
    """Authenticated caller details."""

    secret_name: str
    is_admin: bool


class APIKeyRateLimiter:
    """Sliding-window rate limiter keyed by API key secret name."""

    def __init__(self, limit: int = 100, window_seconds: float = 60.0) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._calls: DefaultDict[str, List[float]] = defaultdict(list)

    def check(self, key_name: str) -> bool:
        """Return True if the key may proceed within the active rate window."""
        now = time.time()
        active = [stamp for stamp in self._calls[key_name] if now - stamp < self._window_seconds]
        self._calls[key_name] = active
        if len(active) >= self._limit:
            return False
        active.append(now)
        return True


class APIKeyAuth:
    """Authenticate incoming API keys against secrets stored in SecretsVault."""

    USER_SECRET_NAME = "IRONCORE_API_KEY"
    ADMIN_SECRET_NAME = "IRONCORE_ADMIN_API_KEY"

    def __init__(
        self,
        vault: SecretsVault,
        rate_limiter: Optional[APIKeyRateLimiter] = None,
    ) -> None:
        self._vault = vault
        self._rate_limiter = rate_limiter or APIKeyRateLimiter()

    def authenticate(
        self,
        raw_api_key: str,
        require_admin: bool = False,
    ) -> Optional[AuthenticatedPrincipal]:
        """Return the authenticated principal or None when credentials fail."""
        for secret_name in (self.ADMIN_SECRET_NAME, self.USER_SECRET_NAME):
            if not self._vault.exists(secret_name):
                continue
            expected = self._vault.get(secret_name, accessor="api.auth")
            if hmac.compare_digest(raw_api_key, expected):
                principal = AuthenticatedPrincipal(
                    secret_name=secret_name,
                    is_admin=(secret_name == self.ADMIN_SECRET_NAME),
                )
                if require_admin and not principal.is_admin:
                    return None
                if not self._rate_limiter.check(secret_name):
                    return None
                return principal
        return None
