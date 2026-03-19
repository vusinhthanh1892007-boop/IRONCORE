"""
IronCore — Phase 7: Enterprise License Manager (JWT-based)
==========================================================

Thay thế cơ chế check env var IRONCORE_EDITION đơn giản bằng JWT validation.
JWT được ký bằng RSA private key (của IronCore), được verify bằng embedded public key.

Features:
  - Đọc license từ file `license.key` hoặc env var IRONCORE_LICENSE_JWT
  - Validate JWT signature với embedded RSA public key
  - Kiểm tra trường `exp` (hạn sử dụng)
  - Kiểm tra trường `features` (danh sách feature được unlock)
  - Fallback về Community Edition nếu JWT invalid/expired

Author: The Optimizer (Claude 4.6) — IronCore V2
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Embedded public key (PEM format, replace with actual IronCore prod key)
# ──────────────────────────────────────────────────────────────────────────────

_EMBEDDED_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0Z3VS5JJcds3xHn/ygWe
vHMBkKABPtCaP0iLMkMVMVnTkHilfM3IrRFEVmhEyFqnFUnJD/xc4iJQbJOJh4R
7IronCoreLicenseValidationPublicKeyPlaceholder0000000000000000000000000
AQIDAQAB
-----END PUBLIC KEY-----"""


@dataclass
class LicenseInfo:
    """Thông tin license đã parse từ JWT."""
    edition: str = "community"
    features: List[str] = field(default_factory=list)
    expires_at: float = 0.0
    licensee: str = ""
    license_id: str = ""
    is_valid: bool = False
    error: str = ""

    @property
    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at

    @property
    def is_enterprise(self) -> bool:
        return self.is_valid and not self.is_expired and self.edition == "enterprise"

    def has_feature(self, feature: str) -> bool:
        return self.is_valid and (feature in self.features or "all" in self.features)


class LicenseManager:
    """
    Enterprise License Manager.

    Validate JWT license key và expose edition/features cho toàn bộ hệ thống.
    Fallback về Community Edition khi JWT không hợp lệ.
    """

    _instance: Optional["LicenseManager"] = None

    def __init__(
        self,
        license_jwt: Optional[str] = None,
        license_key_path: Optional[str] = None,
        public_key_pem: str = _EMBEDDED_PUBLIC_KEY_PEM,
    ):
        self._public_key_pem = public_key_pem
        self._info: Optional[LicenseInfo] = None

        # Tìm JWT từ env var hoặc file
        jwt_token = license_jwt or os.getenv("IRONCORE_LICENSE_JWT", "")

        if not jwt_token:
            key_path = Path(license_key_path or os.getenv("IRONCORE_LICENSE_FILE", "license.key"))
            if key_path.exists():
                jwt_token = key_path.read_text(encoding="utf-8").strip()
                logger.info("[LicenseManager] Loaded license from file: %s", key_path)

        if jwt_token:
            self._info = self._validate(jwt_token)
        else:
            logger.info("[LicenseManager] No license key found. Running Community Edition.")
            self._info = LicenseInfo(edition="community", is_valid=True)

    def _validate(self, jwt_token: str) -> LicenseInfo:
        """Validate JWT và parse payload."""
        parts = jwt_token.strip().split(".")
        if len(parts) != 3:
            return LicenseInfo(error="Invalid JWT format: expected 3 parts")

        try:
            # Decode header và payload (base64url)
            header_raw = self._b64decode(parts[0])
            payload_raw = self._b64decode(parts[1])
            header = json.loads(header_raw.decode("utf-8"))
            payload = json.loads(payload_raw.decode("utf-8"))
        except Exception as exc:
            return LicenseInfo(error=f"JWT decode error: {exc}")

        # Validate signature (via cryptography library nếu có)
        sig_valid = self._verify_signature(parts[0], parts[1], parts[2])
        if not sig_valid:
            logger.warning("[LicenseManager] JWT signature verification failed.")
            return LicenseInfo(error="Invalid license signature")

        # Validate expiry
        exp = payload.get("exp", 0)
        if exp and time.time() > exp:
            return LicenseInfo(
                edition=payload.get("edition", "community"),
                features=payload.get("features", []),
                expires_at=exp,
                licensee=payload.get("licensee", ""),
                license_id=payload.get("license_id", ""),
                is_valid=False,
                error="License expired",
            )

        info = LicenseInfo(
            edition=payload.get("edition", "community"),
            features=payload.get("features", []),
            expires_at=float(exp),
            licensee=payload.get("licensee", ""),
            license_id=payload.get("license_id", ""),
            is_valid=True,
        )
        logger.info(
            "[LicenseManager] License valid | edition=%s licensee=%s features=%s expires_at=%.0f",
            info.edition,
            info.licensee,
            info.features,
            info.expires_at,
        )
        return info

    def _b64decode(self, data: str) -> bytes:
        """Base64url decode (no padding required)."""
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data)

    def _verify_signature(self, header_b64: str, payload_b64: str, sig_b64: str) -> bool:
        """
        Verify RSA-SHA256 JWT signature using embedded public key.
        Fallback: accept if cryptography lib not installed (dev mode).
        """
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding as asym_padding

            pub_key = serialization.load_pem_public_key(
                self._public_key_pem.encode("utf-8")
            )
            message = f"{header_b64}.{payload_b64}".encode("utf-8")
            signature = self._b64decode(sig_b64)
            pub_key.verify(signature, message, asym_padding.PKCS1v15(), hashes.SHA256())  # type: ignore[arg-type]
            return True
        except ImportError:
            # Dev mode: no cryptography lib
            logger.warning("[LicenseManager] 'cryptography' package not installed. Signature NOT verified.")
            return True  # Allow unverified in dev, update for prod
        except Exception as exc:
            logger.error("[LicenseManager] Signature verification error: %s", exc)
            return False

    @property
    def info(self) -> LicenseInfo:
        if self._info is None:
            self._info = LicenseInfo(edition="community", is_valid=True)
        return self._info

    @property
    def is_enterprise(self) -> bool:
        return self.info.is_enterprise

    def has_feature(self, feature: str) -> bool:
        return self.info.has_feature(feature)

    def require_enterprise(self, feature: str = "") -> None:
        """Raise RuntimeError nếu không có enterprise license."""
        if not self.is_enterprise:
            raise RuntimeError(
                f"[IronCore] Enterprise license required"
                + (f" for feature: {feature}" if feature else "")
                + f". Current edition={self.info.edition}, error={self.info.error}"
            )

    @classmethod
    def get_instance(cls) -> "LicenseManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_status(self) -> Dict[str, Any]:
        info = self.info
        return {
            "edition": info.edition,
            "is_valid": info.is_valid,
            "is_enterprise": info.is_enterprise,
            "licensee": info.licensee,
            "expires_at": info.expires_at,
            "features": info.features,
            "error": info.error,
        }
