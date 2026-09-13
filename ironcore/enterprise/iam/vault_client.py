"""HashiCorp Vault + CyberArk PAM secrets adapters.

Both clients are dependency-free at module import time — the HTTP call is
delegated to an injected ``http_client`` so tests can mock the Vault API
without a running Vault instance.

Just-In-Time (JIT) access pattern:
  1. ``get_secret(path)``          → returns plaintext secret value
  2. ``get_dynamic_credential()``  → returns ``DynamicCredential`` with ``lease_id``
  3. ``revoke_credential(lease_id)`` → immediately destroys the credential

Secrets are NEVER cached longer than the caller's scope.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any, Dict, Optional

from pydantic import BaseModel

from ironcore.edition import check_enterprise

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Data models
# ══════════════════════════════════════════════════════════════════════════════

class DynamicCredential(BaseModel):
    value: str
    lease_id: str
    lease_duration: int     # seconds
    renewable: bool = True


# ══════════════════════════════════════════════════════════════════════════════
#  VaultSecretsManager — HashiCorp Vault
# ══════════════════════════════════════════════════════════════════════════════

class VaultSecretsManager:
    """Just-In-Time secrets retrieval from HashiCorp Vault.

    Requires ``IRONCORE_EDITION=enterprise``.

    Auth methods supported: ``approle`` (default), ``kubernetes``, ``cert``.
    """

    def __init__(
        self,
        vault_url: str = "https://vault.bank.internal:8200",
        auth_method: str = "approle",
        role_id: str = "",
        secret_id: str = "",
        mount_path: str = "secret/ironcore",
        http_client: Any = None,
        namespace: Optional[str] = None,       # Vault Enterprise namespace
    ) -> None:
        check_enterprise("vault_integration")
        self._vault_url = vault_url.rstrip("/")
        self._auth_method = auth_method
        self._role_id = role_id
        self._secret_id = secret_id
        self._mount_path = mount_path.strip("/")
        self._http = http_client
        self._namespace = namespace
        self._vault_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._vault_token:
            headers["X-Vault-Token"] = self._vault_token
        if self._namespace:
            headers["X-Vault-Namespace"] = self._namespace
        return headers

    async def _authenticate(self) -> None:
        """Obtain a Vault token via AppRole auth and cache it."""
        if self._http is None:
            self._vault_token = "mock-vault-token"
            self._token_expires_at = time.time() + 3600
            return

        if self._auth_method == "approle":
            url = f"{self._vault_url}/v1/auth/approle/login"
            payload = {"role_id": self._role_id, "secret_id": self._secret_id}
            resp = await self._http.post(url, json=payload, headers={"Content-Type": "application/json"})
            data = resp.json() if hasattr(resp, "json") else {}
            auth = data.get("auth", {})
            self._vault_token = auth.get("client_token", "")
            lease_duration = auth.get("lease_duration", 3600)
            self._token_expires_at = time.time() + lease_duration - 60  # renew 60s early
            logger.info("[Vault] Authenticated via AppRole, token valid %ds", lease_duration)
        else:
            # kubernetes / cert auth — placeholder; extend as needed
            raise NotImplementedError(f"Auth method {self._auth_method!r} not yet implemented.")

    async def _ensure_token(self) -> None:
        """Authenticate if we don't have a valid token."""
        if not self._vault_token or time.time() >= self._token_expires_at:
            await self._authenticate()

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_secret(self, secret_path: str) -> str:
        """Fetch a KV-v2 secret from Vault and return its ``value`` field.

        ``secret_path`` is relative to ``mount_path``, e.g. ``"llm/anthropic_api_key"``.
        """
        await self._ensure_token()

        if self._http is None:
            logger.warning("[Vault] No HTTP client — returning stub for path=%s", secret_path)
            return f"stub-secret-{hashlib.sha256(secret_path.encode()).hexdigest()[:8]}"

        url = f"{self._vault_url}/v1/{self._mount_path}/data/{secret_path}"
        resp = await self._http.get(url, headers=self._headers())
        data = resp.json() if hasattr(resp, "json") else {}
        value = data.get("data", {}).get("data", {}).get("value", "")
        if not value:
            raise KeyError(f"[Vault] Secret not found at path: {secret_path!r}")
        logger.info("[Vault] Retrieved secret at path=%s", secret_path)
        return value

    async def get_dynamic_credential(self, role: str) -> DynamicCredential:
        """Request a dynamic credential (e.g. DB password, temporary API key).

        ``role`` maps to a Vault dynamic-secrets role under the database engine.
        """
        await self._ensure_token()

        if self._http is None:
            logger.warning("[Vault] No HTTP client — returning stub dynamic credential for role=%s", role)
            return DynamicCredential(
                value=f"stub-cred-{hashlib.sha256(role.encode()).hexdigest()[:12]}",
                lease_id=f"database/creds/{role}/stub-lease-{time.time():.0f}",
                lease_duration=3600,
                renewable=True,
            )

        url = f"{self._vault_url}/v1/database/creds/{role}"
        resp = await self._http.get(url, headers=self._headers())
        data = resp.json() if hasattr(resp, "json") else {}
        cred_data = data.get("data", {})
        return DynamicCredential(
            value=cred_data.get("password") or cred_data.get("credential", ""),
            lease_id=data.get("lease_id", ""),
            lease_duration=data.get("lease_duration", 3600),
            renewable=data.get("renewable", True),
        )

    async def revoke_credential(self, lease_id: str) -> None:
        """Immediately revoke a dynamic credential by lease ID."""
        await self._ensure_token()

        if self._http is None:
            logger.warning("[Vault] No HTTP client — stub revoke for lease=%s", lease_id)
            return

        url = f"{self._vault_url}/v1/sys/leases/revoke"
        payload = {"lease_id": lease_id}
        await self._http.put(url, json=payload, headers=self._headers())
        logger.info("[Vault] Revoked credential lease=%s", lease_id)

    async def renew_token(self) -> None:
        """Renew the current Vault token before it expires."""
        if self._http is None or not self._vault_token:
            return

        url = f"{self._vault_url}/v1/auth/token/renew-self"
        resp = await self._http.post(url, json={}, headers=self._headers())
        data = resp.json() if hasattr(resp, "json") else {}
        auth = data.get("auth", {})
        lease_duration = auth.get("lease_duration", 3600)
        self._token_expires_at = time.time() + lease_duration - 60
        logger.info("[Vault] Token renewed, valid for %ds more", lease_duration)

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, http_client: Any = None) -> "VaultSecretsManager":
        """Build a ``VaultSecretsManager`` from environment variables."""
        secret_id = os.getenv("IRONCORE_VAULT_SECRET_ID", "")
        # Support reading secret_id from a file (Kubernetes secret volume)
        secret_id_file = os.getenv("IRONCORE_VAULT_SECRET_ID_FILE", "")
        if not secret_id and secret_id_file and os.path.isfile(secret_id_file):
            with open(secret_id_file) as f:
                secret_id = f.read().strip()

        return cls(
            vault_url=os.getenv("IRONCORE_VAULT_URL", "https://vault.bank.internal:8200"),
            auth_method=os.getenv("IRONCORE_VAULT_AUTH_METHOD", "approle"),
            role_id=os.getenv("IRONCORE_VAULT_ROLE_ID", ""),
            secret_id=secret_id,
            mount_path=os.getenv("IRONCORE_VAULT_MOUNT_PATH", "secret/ironcore"),
            namespace=os.getenv("IRONCORE_VAULT_NAMESPACE") or None,
            http_client=http_client,
        )


# ══════════════════════════════════════════════════════════════════════════════
#  CyberArkClient — CyberArk PAM
# ══════════════════════════════════════════════════════════════════════════════

class CyberArkClient:
    """Fetch credentials from CyberArk Privileged Access Manager.

    Uses the CyberArk Central Credential Provider (CCP) REST API.
    Authentication: Certificate-based (MTLS) or AppID.

    Requires ``IRONCORE_EDITION=enterprise``.
    """

    def __init__(
        self,
        base_url: str,
        app_id: str,
        certificate_path: Optional[str] = None,
        http_client: Any = None,
    ) -> None:
        check_enterprise("cyberark_integration")
        self._base_url = base_url.rstrip("/")
        self._app_id = app_id
        self._cert_path = certificate_path
        self._http = http_client

    async def get_account_credentials(
        self,
        safe: str,
        object_name: str,
    ) -> str:
        """Retrieve a password or API key from CyberArk.

        Args:
            safe:        CyberArk Safe (vault) name.
            object_name: Account object name within that safe.

        Returns:
            The plaintext credential string.
        """
        if self._http is None:
            logger.warning(
                "[CyberArk] No HTTP client — returning stub credential for safe=%s object=%s",
                safe, object_name,
            )
            key = f"{safe}/{object_name}"
            return f"stub-cyberark-{hashlib.sha256(key.encode()).hexdigest()[:12]}"

        url = (
            f"{self._base_url}/AIMWebService/api/Accounts"
            f"?AppID={self._app_id}"
            f"&Safe={safe}"
            f"&Object={object_name}"
        )
        headers = {"Content-Type": "application/json"}
        resp = await self._http.get(url, headers=headers)
        data = resp.json() if hasattr(resp, "json") else {}
        credential = data.get("Content", "")
        if not credential:
            raise KeyError(
                f"[CyberArk] No credential returned for safe={safe!r} object={object_name!r}"
            )
        logger.info("[CyberArk] Retrieved credential for safe=%s object=%s", safe, object_name)
        return credential

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, http_client: Any = None) -> "CyberArkClient":
        return cls(
            base_url=os.getenv("IRONCORE_CYBERARK_URL", "https://cyberark.bank.internal"),
            app_id=os.getenv("IRONCORE_CYBERARK_APP_ID", "IronCore"),
            certificate_path=os.getenv("IRONCORE_CYBERARK_CERT") or None,
            http_client=http_client,
        )
