"""
Role-based access control for IronCore policy enforcement.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Set

from ironcore.security.policy_engine import BaseRule, PolicyResult, PolicyVerdict

logger = logging.getLogger(__name__)


class Role(str, Enum):
    """Supported caller roles."""

    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class Permission(str, Enum):
    """Permissions granted to roles and enforced by RBACRule."""

    READ_HISTORY = "read_history"
    DISPATCH_LOW = "dispatch_low"
    DISPATCH_MEDIUM = "dispatch_medium"
    DISPATCH_HIGH = "dispatch_high"
    DISPATCH_CRITICAL = "dispatch_critical"
    MANAGE_SECRETS = "manage_secrets"
    MANAGE_RULES = "manage_rules"
    VIEW_AUDIT = "view_audit"


ROLE_PERMISSIONS: Dict[Role, Set[Permission]] = {
    Role.VIEWER: {
        Permission.READ_HISTORY,
        Permission.VIEW_AUDIT,
    },
    Role.OPERATOR: {
        Permission.READ_HISTORY,
        Permission.DISPATCH_LOW,
        Permission.DISPATCH_MEDIUM,
        Permission.VIEW_AUDIT,
    },
    Role.ADMIN: set(Permission),
}

_RISK_PERMISSION_MAP: Dict[str, Permission] = {
    "LOW": Permission.DISPATCH_LOW,
    "MEDIUM": Permission.DISPATCH_MEDIUM,
    "HIGH": Permission.DISPATCH_HIGH,
    "CRITICAL": Permission.DISPATCH_CRITICAL,
}

_HEADER = {"alg": "HS256", "typ": "JWT"}
_DEFAULT_SECRET = os.environ.get("IRONCORE_RBAC_JWT_SECRET", secrets.token_urlsafe(32))
_DEFAULT_READ_ONLY_TOOLS = {
    "history_read",
    "policy_status",
    "view_audit",
}


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}".encode("ascii"))


def issue_token(
    role: Role,
    expires_in_seconds: int,
    secret: Optional[str] = None,
) -> str:
    """
    Issue a signed JWT for a specific role.

    Args:
        role: Role to encode in the token.
        expires_in_seconds: TTL for the token.
        secret: Optional HMAC secret override.

    Returns:
        Compact JWT string signed with HS256.
    """
    issued_at = int(time.time())
    payload = {
        "role": role.value,
        "iat": issued_at,
        "exp": issued_at + max(1, expires_in_seconds),
    }
    secret_bytes = (secret or _DEFAULT_SECRET).encode("utf-8")
    header_segment = _b64url_encode(json.dumps(_HEADER, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    payload_segment = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature = hmac.new(secret_bytes, signing_input, hashlib.sha256).digest()
    return f"{header_segment}.{payload_segment}.{_b64url_encode(signature)}"


def validate_token(
    token: str,
    secret: Optional[str] = None,
) -> Optional[Role]:
    """
    Validate a JWT and return its role when valid.

    Args:
        token: Compact JWT string.
        secret: Optional HMAC secret override.

    Returns:
        Role if the token is valid and unexpired, otherwise None.
    """
    try:
        header_segment, payload_segment, signature_segment = token.split(".")
        signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
        expected_signature = hmac.new(
            (secret or _DEFAULT_SECRET).encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
        provided_signature = _b64url_decode(signature_segment)
        if not hmac.compare_digest(expected_signature, provided_signature):
            return None

        header = json.loads(_b64url_decode(header_segment))
        payload = json.loads(_b64url_decode(payload_segment))
        if header.get("alg") != "HS256":
            return None
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return Role(payload["role"])
    except (KeyError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("[RBAC] Rejected invalid token payload.")
        return None


class RBACRule(BaseRule):
    """
    Enforce role permissions for action dispatch and control-plane operations.

    Context conventions:
      - ``role``: explicit caller role as ``Role`` or role string.
      - ``auth_token``: JWT to validate when ``role`` is absent.
      - ``required_permission``: explicit permission override.
      - ``risk_level``: action risk name used for dispatch permission mapping.
    """

    def __init__(
        self,
        tool_permissions: Optional[Mapping[str, Permission | str]] = None,
        read_only_tools: Optional[Set[str]] = None,
        token_secret: Optional[str] = None,
    ) -> None:
        self._tool_permissions = {
            tool_name: permission if isinstance(permission, Permission) else Permission(permission)
            for tool_name, permission in (tool_permissions or {}).items()
        }
        self._read_only_tools = set(read_only_tools or _DEFAULT_READ_ONLY_TOOLS)
        self._token_secret = token_secret

    @property
    def name(self) -> str:
        return "rbac"

    def evaluate(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PolicyResult:
        del args
        role = self._extract_role(context)
        if role is None:
            return PolicyResult(
                verdict=PolicyVerdict.DENY,
                rule_name=self.name,
                reason="Caller role is missing or token validation failed.",
            )

        required_permission = self._resolve_permission(tool_name, context)
        allowed_permissions = ROLE_PERMISSIONS[role]
        if required_permission not in allowed_permissions:
            return PolicyResult(
                verdict=PolicyVerdict.DENY,
                rule_name=self.name,
                reason=(
                    f"Role '{role.value}' lacks permission '{required_permission.value}' "
                    f"for tool '{tool_name}'."
                ),
                metadata={
                    "role": role.value,
                    "required_permission": required_permission.value,
                },
            )

        return PolicyResult(
            verdict=PolicyVerdict.ALLOW,
            rule_name=self.name,
            reason=(
                f"Role '{role.value}' authorized for permission "
                f"'{required_permission.value}'."
            ),
            metadata={
                "role": role.value,
                "required_permission": required_permission.value,
            },
        )

    def _extract_role(self, context: Dict[str, Any]) -> Optional[Role]:
        raw_role = context.get("role")
        if isinstance(raw_role, Role):
            return raw_role
        if isinstance(raw_role, str):
            try:
                return Role(raw_role.lower())
            except ValueError:
                return None

        token = context.get("auth_token")
        if isinstance(token, str) and token:
            return validate_token(token, secret=self._token_secret)
        return None

    def _resolve_permission(
        self,
        tool_name: str,
        context: Dict[str, Any],
    ) -> Permission:
        explicit_permission = context.get("required_permission")
        if isinstance(explicit_permission, Permission):
            return explicit_permission
        if isinstance(explicit_permission, str):
            return Permission(explicit_permission.lower())

        if tool_name in self._tool_permissions:
            return self._tool_permissions[tool_name]
        if tool_name in self._read_only_tools or context.get("read_only") is True:
            return Permission.READ_HISTORY

        risk_level = str(context.get("risk_level", "LOW")).upper()
        return _RISK_PERMISSION_MAP.get(risk_level, Permission.DISPATCH_LOW)
