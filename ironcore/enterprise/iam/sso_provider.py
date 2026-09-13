"""SSO / OIDC provider for Enterprise IAM.

Supports:
  - Azure Entra ID (Azure AD)
  - Okta
  - On-premise ADFS (treated as generic OIDC)
  - Generic OIDC

Authorization-Code + PKCE flow:
  1. ``get_authorization_url(state, code_challenge)`` → redirect user to IdP
  2. IdP redirects back with ``code`` + original ``state``
  3. ``exchange_code(code, state, code_verifier)`` → ``SSOUserInfo``
  4. ``get_user_groups(access_token)`` → IronCore RBAC roles

No hard external dependencies at import time.  The ``http_client`` is injected
so tests can stub the HTTP layer without needing a real IdP.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import time
import urllib.parse
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ironcore.edition import check_enterprise

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Enums & data models
# ══════════════════════════════════════════════════════════════════════════════

class SSOProvider(str, Enum):
    AZURE_ENTRA       = "azure_entra"   # Azure AD / Microsoft Entra ID
    OKTA              = "okta"
    ACTIVE_DIRECTORY  = "adfs"          # On-premise ADFS (SAML/OIDC)
    GENERIC_OIDC      = "oidc"


class SSOConfig(BaseModel):
    provider: SSOProvider
    client_id: str
    client_secret: str                              # fetched from Vault at startup
    tenant_id: Optional[str] = None                # Azure: tenant / directory ID
    domain: Optional[str] = None                   # Okta: yourorg.okta.com
    redirect_uri: str = "https://ironcore.internal/auth/callback"
    scopes: List[str] = ["openid", "email", "profile", "groups"]
    group_role_mapping: Dict[str, str] = Field(
        default_factory=dict
    )  # e.g. {"IT-Admins": "admin", "RiskManagement": "approver"}
    # Optional override of auto-derived discovery URL
    discovery_url: Optional[str] = None


class SSOUserInfo(BaseModel):
    sub: str                           # Subject identifier from IdP
    email: str
    display_name: str = ""
    employee_id: Optional[str] = None
    groups: List[str] = Field(default_factory=list)     # Raw IdP groups
    roles: List[str] = Field(default_factory=list)      # Mapped IronCore RBAC roles
    access_token: Optional[str] = None
    id_token: Optional[str] = None
    expires_at: Optional[float] = None


# ══════════════════════════════════════════════════════════════════════════════
#  PKCE helpers
# ══════════════════════════════════════════════════════════════════════════════

def generate_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for PKCE S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


# ══════════════════════════════════════════════════════════════════════════════
#  Authorization-endpoint derivation
# ══════════════════════════════════════════════════════════════════════════════

def _derive_endpoints(config: SSOConfig) -> Dict[str, str]:
    """Return {'auth_endpoint': ..., 'token_endpoint': ..., 'userinfo_endpoint': ...}."""
    p = config.provider
    if p == SSOProvider.AZURE_ENTRA:
        tid = config.tenant_id or "common"
        base = f"https://login.microsoftonline.com/{tid}/oauth2/v2.0"
        return {
            "auth_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "userinfo_endpoint": "https://graph.microsoft.com/oidc/userinfo",
            "jwks_uri": f"https://login.microsoftonline.com/{tid}/discovery/v2.0/keys",
        }
    if p == SSOProvider.OKTA:
        domain = config.domain or "yourorg.okta.com"
        base = f"https://{domain}/oauth2/v1"
        return {
            "auth_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "userinfo_endpoint": f"{base}/userinfo",
            "jwks_uri": f"https://{domain}/oauth2/v1/keys",
        }
    if p == SSOProvider.ACTIVE_DIRECTORY:
        domain = config.domain or "adfs.internal"
        base = f"https://{domain}/adfs"
        return {
            "auth_endpoint": f"{base}/oauth2/authorize",
            "token_endpoint": f"{base}/oauth2/token",
            "userinfo_endpoint": f"{base}/userinfo",
            "jwks_uri": f"{base}/discovery/keys",
        }
    # Generic OIDC — requires discovery_url
    if config.discovery_url:
        disc = config.discovery_url.rstrip("/")
        return {
            "auth_endpoint": f"{disc}/authorize",
            "token_endpoint": f"{disc}/token",
            "userinfo_endpoint": f"{disc}/userinfo",
            "jwks_uri": f"{disc}/keys",
        }
    raise ValueError("Generic OIDC provider requires 'discovery_url' in SSOConfig.")


# ══════════════════════════════════════════════════════════════════════════════
#  SSOManager
# ══════════════════════════════════════════════════════════════════════════════

class SSOManager:
    """OIDC Authorization-Code + PKCE flow manager.

    Requires ``IRONCORE_EDITION=enterprise``.
    """

    def __init__(
        self,
        provider: SSOProvider,
        config: SSOConfig,
        http_client: Any = None,
    ) -> None:
        check_enterprise("enterprise_sso")
        self._provider = provider
        self._config = config
        self._http = http_client
        self._endpoints = _derive_endpoints(config)
        # In-memory state store for active PKCE/nonce pairs (token_id → verifier)
        self._pending_states: Dict[str, str] = {}

    # ── PKCE helpers exposed for tests ────────────────────────────────────────

    @staticmethod
    def generate_pkce_pair() -> tuple[str, str]:
        return generate_pkce_pair()

    # ── Authorization URL ─────────────────────────────────────────────────────

    def get_authorization_url(self, state: str, code_challenge: str) -> str:
        """Build the IdP login redirect URL (PKCE, S256 method)."""
        params = {
            "response_type": "code",
            "client_id": self._config.client_id,
            "redirect_uri": self._config.redirect_uri,
            "scope": " ".join(self._config.scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        url = self._endpoints["auth_endpoint"] + "?" + urllib.parse.urlencode(params)
        logger.debug("[SSO] Authorization URL generated for state=%s", state)
        return url

    # ── Token exchange ─────────────────────────────────────────────────────────

    async def exchange_code(
        self,
        code: str,
        state: str,
        code_verifier: str,
    ) -> SSOUserInfo:
        """Exchange authorization code for tokens and return ``SSOUserInfo``.

        Validates the presence of ``sub`` in the ID token claims.
        Full JWT signature verification requires a ``jwks_client`` — when
        *http_client* is ``None`` the token is accepted as-is (for tests).
        """
        if self._http is None:
            logger.warning("[SSO] No HTTP client — returning stub SSOUserInfo for code=%s", code)
            return SSOUserInfo(
                sub=f"stub|{code}",
                email="stub@example.com",
                display_name="Stub User",
                access_token="stub-access-token",
                id_token="stub-id-token",
                expires_at=time.time() + 3600,
            )

        payload = {
            "grant_type": "authorization_code",
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
            "redirect_uri": self._config.redirect_uri,
            "code": code,
            "code_verifier": code_verifier,
        }
        resp = await self._http.post(
            self._endpoints["token_endpoint"],
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token_data: Dict[str, Any] = resp.json() if hasattr(resp, "json") else {}

        if "error" in token_data:
            raise ValueError(
                f"[SSO] Token exchange failed: {token_data.get('error_description', token_data['error'])}"
            )

        access_token = token_data.get("access_token", "")
        id_token = token_data.get("id_token", "")
        expires_in = token_data.get("expires_in", 3600)

        # Decode the JWT claims (without verification — verification needs JWKS fetch)
        claims = _decode_jwt_claims_unverified(id_token)
        sub = claims.get("sub", "")
        email = claims.get("email") or claims.get("upn") or claims.get("preferred_username", "")
        name = claims.get("name", "")

        if not sub:
            raise ValueError("[SSO] ID token is missing 'sub' claim.")

        # Fetch user groups from IdP if enabled
        groups: List[str] = []
        try:
            groups = await self.get_user_groups(access_token)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[SSO] Could not fetch groups: %s", exc)

        roles = self._map_groups_to_roles(groups)

        user = SSOUserInfo(
            sub=sub,
            email=email,
            display_name=name,
            groups=groups,
            roles=roles,
            access_token=access_token,
            id_token=id_token,
            expires_at=time.time() + expires_in,
        )
        logger.info("[SSO] User authenticated: sub=%s email=%s roles=%s", sub, email, roles)
        return user

    # ── Group resolution ───────────────────────────────────────────────────────

    async def get_user_groups(self, access_token: str) -> List[str]:
        """Fetch IdP groups for the token bearer and return group names."""
        if self._http is None:
            return []

        if self._provider == SSOProvider.AZURE_ENTRA:
            url = "https://graph.microsoft.com/v1.0/me/memberOf"
            resp = await self._http.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )
            data = resp.json() if hasattr(resp, "json") else {}
            return [
                g.get("displayName", g.get("id", ""))
                for g in data.get("value", [])
            ]

        if self._provider == SSOProvider.OKTA:
            url = f"https://{self._config.domain}/api/v1/users/me/groups"
            resp = await self._http.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )
            data = resp.json() if hasattr(resp, "json") else []
            return [g.get("profile", {}).get("name", "") for g in data]

        # ADFS / Generic OIDC: groups claim in userinfo or ID token
        url = self._endpoints["userinfo_endpoint"]
        resp = await self._http.get(
            url, headers={"Authorization": f"Bearer {access_token}"}
        )
        data = resp.json() if hasattr(resp, "json") else {}
        groups = data.get("groups", [])
        return groups if isinstance(groups, list) else []

    # ── Role mapping ───────────────────────────────────────────────────────────

    def _map_groups_to_roles(self, groups: List[str]) -> List[str]:
        """Map IdP groups to IronCore RBAC roles using config mapping."""
        roles: List[str] = []
        mapping = self._config.group_role_mapping
        for group in groups:
            if group in mapping:
                role = mapping[group]
                if role not in roles:
                    roles.append(role)
        return roles

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, http_client: Any = None) -> "SSOManager":
        """Build a ``SSOManager`` from environment variables."""
        provider_raw = os.getenv("IRONCORE_SSO_PROVIDER", "oidc")
        provider = SSOProvider(provider_raw)
        scopes_raw = os.getenv("IRONCORE_SSO_SCOPES", "openid email profile groups")
        config = SSOConfig(
            provider=provider,
            client_id=os.getenv("IRONCORE_SSO_CLIENT_ID", ""),
            client_secret=os.getenv("IRONCORE_SSO_CLIENT_SECRET", ""),
            tenant_id=os.getenv("IRONCORE_SSO_TENANT_ID") or None,
            domain=os.getenv("IRONCORE_SSO_DOMAIN") or None,
            redirect_uri=os.getenv(
                "IRONCORE_SSO_REDIRECT_URI", "https://ironcore.internal/auth/callback"
            ),
            scopes=scopes_raw.split(),
            discovery_url=os.getenv("IRONCORE_SSO_DISCOVERY_URL") or None,
        )
        return cls(provider=provider, config=config, http_client=http_client)


# ══════════════════════════════════════════════════════════════════════════════
#  Utility — unverified JWT decode (for tests / fallback)
# ══════════════════════════════════════════════════════════════════════════════

def _decode_jwt_claims_unverified(token: str) -> Dict[str, Any]:
    """Decode JWT payload without signature verification.

    Suitable only for extracting non-security-critical claims (email, name).
    Signature MUST be verified via JWKS in production code.
    """
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload_b64 = parts[1]
        # Add padding
        payload_b64 += "=" * (-len(payload_b64) % 4)
        import json as _json
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return _json.loads(payload_bytes)
    except Exception:  # noqa: BLE001
        return {}
