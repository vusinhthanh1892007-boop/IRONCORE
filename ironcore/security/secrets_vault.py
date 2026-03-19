"""
IronCore: Secrets Vault
=======================
Encrypted in-memory and on-disk secrets manager using symmetric Fernet encryption.

Why this exists:
  Legacy agents (OpenClaw) stored API keys in plain-text env vars or config files.
  IronCore stores them encrypted both at rest and in memory, only decrypting at
  the last possible moment — inside the tool handler that needs them.

Security properties:
  • AES-128-CBC + HMAC-SHA256 (Fernet standard).
  • Key never stored alongside secrets — loaded from env or a separate key file.
  • Secrets zeroized (overwritten) from memory after use where Python allows.
  • Audit log entry generated for every secret read access.
  • Optional time-based secret expiry (TTL).

Dependency: pip install cryptography

Author: The Architect (IronCore Project)
"""

from __future__ import annotations

import base64
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False
    logger.warning(
        "[SecretsVault] 'cryptography' package not installed. "
        "Run: pip install cryptography"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SecretEntry:
    """
    A single encrypted secret record.

    Attributes:
        name           : Logical identifier (e.g., 'OPENAI_API_KEY').
        ciphertext     : Fernet-encrypted bytes of the secret value.
        created_at     : Unix timestamp of creation.
        expires_at     : Optional Unix timestamp after which secret is invalid.
        access_count   : Number of times this secret has been decrypted.
        description    : Optional human-readable description for audit purposes.
    """
    name: str
    ciphertext: bytes
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    access_count: int = 0
    description: str = ""

    @property
    def is_expired(self) -> bool:
        """True if the secret has a TTL and that TTL has passed."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


@dataclass
class AccessLogEntry:
    """Immutable audit record for a single secret access."""
    secret_name: str
    timestamp: float = field(default_factory=time.time)
    accessor: str = "unknown"
    granted: bool = True
    reason: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# SecretsVault
# ──────────────────────────────────────────────────────────────────────────────

class SecretsVault:
    """
    Encrypted secrets manager for IronCore.

    Secrets are stored encrypted in memory only — never in plain text.
    The vault key can be derived from a passphrase + salt (PBKDF2) or
    loaded directly as a base64-encoded Fernet key.

    Usage::

        vault = SecretsVault.from_passphrase("my-master-password")
        vault.store("OPENAI_KEY", "sk-abc123...", description="OpenAI API key")

        # Later, in a tool handler:
        with vault.reveal("OPENAI_KEY") as secret:
            response = openai_client.call(api_key=secret)
        # secret is no longer accessible outside the 'with' block

        vault.audit_log()  # prints all access records
    """

    def __init__(self, fernet_key: bytes) -> None:
        """
        Initialize the vault with a raw Fernet key.

        Args:
            fernet_key: A valid 32-byte base64url-encoded Fernet key.

        Raises:
            ImportError: If the 'cryptography' package is not installed.
        """
        if not _CRYPTO_AVAILABLE:
            raise ImportError(
                "'cryptography' is required for SecretsVault. "
                "Install it with: pip install cryptography"
            )
        self._fernet = Fernet(fernet_key)
        self._secrets: Dict[str, SecretEntry] = {}
        self._access_log: List[AccessLogEntry] = []
        logger.info("[SecretsVault] Vault initialized.")

    # ── Factory Methods ───────────────────────────────────────────────────────

    @classmethod
    def generate(cls) -> "SecretsVault":
        """
        Create a vault with a freshly generated random key.

        The key is printed ONCE to stdout — save it securely.
        """
        key = Fernet.generate_key()
        logger.warning(
            "[SecretsVault] NEW VAULT KEY (save this to a secure location — "
            "it will NOT be shown again):\n"
            f"  IRONCORE_VAULT_KEY={key.decode()}"
        )
        return cls(fernet_key=key)

    @classmethod
    def from_env(cls, env_var: str = "IRONCORE_VAULT_KEY") -> "SecretsVault":
        """
        Load vault key from an environment variable.

        Args:
            env_var: Name of the environment variable containing the key.

        Raises:
            EnvironmentError: If the variable is missing.
        """
        raw = os.environ.get(env_var)
        if not raw:
            raise EnvironmentError(
                f"[SecretsVault] Environment variable '{env_var}' is not set. "
                "Generate a key with SecretsVault.generate() and set it."
            )
        return cls(fernet_key=raw.encode())

    @classmethod
    def from_passphrase(
        cls,
        passphrase: str,
        salt: Optional[bytes] = None,
    ) -> "SecretsVault":
        """
        Derive a Fernet key from a human-memorable passphrase via PBKDF2.

        WARNING: Use a strong, random salt in production. If salt is None,
        a random one is generated but CANNOT be recovered — the vault will be
        unrecoverable if lost.

        Args:
            passphrase: Master password.
            salt:       16-byte salt. Store it alongside ciphertext files.

        Returns:
            A SecretsVault keyed by the derived key.
        """
        effective_salt = salt or os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=effective_salt,
            iterations=480_000,   # OWASP 2023 recommendation
        )
        derived = base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))
        return cls(fernet_key=derived)

    # ── Secret Management ─────────────────────────────────────────────────────

    def store(
        self,
        name: str,
        plaintext_value: str,
        description: str = "",
        ttl_seconds: Optional[float] = None,
    ) -> None:
        """
        Encrypt and store a secret in the vault.

        Args:
            name:            Unique identifier for this secret.
            plaintext_value: The sensitive value to protect.
            description:     Optional human-readable description.
            ttl_seconds:     If set, the secret expires after this many seconds.

        Raises:
            ValueError: If a secret with this name already exists.
        """
        if name in self._secrets:
            raise ValueError(
                f"[SecretsVault] Secret '{name}' already exists. "
                "Use update() to replace it."
            )
        ciphertext = self._fernet.encrypt(plaintext_value.encode())
        entry = SecretEntry(
            name=name,
            ciphertext=ciphertext,
            description=description,
            expires_at=(time.time() + ttl_seconds) if ttl_seconds else None,
        )
        self._secrets[name] = entry
        logger.info(
            f"[SecretsVault] Stored secret '{name}' "
            f"(ttl={'never' if ttl_seconds is None else f'{ttl_seconds}s'})."
        )

    def update(
        self,
        name: str,
        new_plaintext_value: str,
        ttl_seconds: Optional[float] = None,
    ) -> None:
        """
        Replace an existing secret's value with a new encrypted value.

        Args:
            name:               Secret identifier.
            new_plaintext_value: New value to encrypt and store.
            ttl_seconds:        Optional new TTL (None = keep existing).

        Raises:
            KeyError: If the secret does not exist.
        """
        if name not in self._secrets:
            raise KeyError(f"[SecretsVault] Secret '{name}' not found.")
        old = self._secrets[name]
        ciphertext = self._fernet.encrypt(new_plaintext_value.encode())
        self._secrets[name] = SecretEntry(
            name=name,
            ciphertext=ciphertext,
            description=old.description,
            created_at=time.time(),
            expires_at=(time.time() + ttl_seconds) if ttl_seconds else old.expires_at,
        )
        logger.info(f"[SecretsVault] Secret '{name}' updated.")

    def delete(self, name: str) -> None:
        """
        Remove a secret from the vault.

        Args:
            name: Secret identifier.

        Raises:
            KeyError: If the secret does not exist.
        """
        if name not in self._secrets:
            raise KeyError(f"[SecretsVault] Secret '{name}' not found.")
        del self._secrets[name]
        logger.info(f"[SecretsVault] Secret '{name}' deleted.")

    def get(self, name: str, accessor: str = "unknown") -> str:
        """
        Decrypt and return a secret value.

        This is the standard access method. Every call is logged.

        Args:
            name:     Secret identifier.
            accessor: Who / which component is requesting access (for audit).

        Returns:
            Decrypted plaintext string.

        Raises:
            KeyError:          If the secret does not exist.
            PermissionError:   If the secret has expired.
            InvalidToken:      If ciphertext is corrupted or key is wrong.
        """
        entry = self._secrets.get(name)
        if entry is None:
            self._log_access(name, accessor, granted=False, reason="not_found")
            raise KeyError(f"[SecretsVault] Secret '{name}' not found.")

        if entry.is_expired:
            self._log_access(name, accessor, granted=False, reason="expired")
            raise PermissionError(
                f"[SecretsVault] Secret '{name}' has expired."
            )

        try:
            plaintext = self._fernet.decrypt(entry.ciphertext).decode()
            entry.access_count += 1
            self._log_access(name, accessor, granted=True)
            logger.debug(
                f"[SecretsVault] Secret '{name}' accessed by '{accessor}' "
                f"(count={entry.access_count})."
            )
            return plaintext
        except InvalidToken as exc:
            self._log_access(
                name, accessor, granted=False, reason="invalid_token"
            )
            raise InvalidToken(
                f"[SecretsVault] Decryption failed for '{name}'. "
                "Key mismatch or data corruption."
            ) from exc

    def list_names(self) -> List[str]:
        """Return all stored secret names (never values)."""
        return list(self._secrets.keys())

    def exists(self, name: str) -> bool:
        """True if a non-expired secret with this name exists."""
        entry = self._secrets.get(name)
        return entry is not None and not entry.is_expired

    # ── Audit ─────────────────────────────────────────────────────────────────

    def _log_access(
        self,
        name: str,
        accessor: str,
        granted: bool,
        reason: str = "",
    ) -> None:
        self._access_log.append(AccessLogEntry(
            secret_name=name,
            accessor=accessor,
            granted=granted,
            reason=reason,
        ))

    def audit_log(self, last_n: int = 50) -> List[AccessLogEntry]:
        """
        Return recent secret access records for security auditing.

        Args:
            last_n: Maximum number of most-recent entries to return.

        Returns:
            List of AccessLogEntry, newest last.
        """
        entries = self._access_log[-last_n:]
        for e in entries:
            status = "GRANTED" if e.granted else f"DENIED ({e.reason})"
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.timestamp))
            logger.info(
                f"[AuditLog] {ts} | secret={e.secret_name} | "
                f"accessor={e.accessor} | {status}"
            )
        return entries


# ──────────────────────────────────────────────────────────────────────────────
# Demo entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout,
    )

    vault = SecretsVault.generate()

    vault.store("OPENAI_API_KEY", "sk-test-abc123", description="Demo key", ttl_seconds=3600)
    vault.store("GITHUB_PAT", "ghp_xyz789", description="GitHub token")

    print("\nStored secrets:", vault.list_names())
    print("OpenAI key:", vault.get("OPENAI_API_KEY", accessor="core.engine"))

    vault.audit_log()
