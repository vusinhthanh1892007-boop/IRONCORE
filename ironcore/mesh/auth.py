"""Agent-to-agent JWT authentication for IronCore multi-node mesh.

Implements HS256 JWTs using only the Python standard library (no external
JWT packages required) so the mesh module stays dependency-free.

Token claims::

    {
        "alg": "HS256",
        "typ": "JWT"
    }.{
        "sub":          "<node_id>",
        "iss":          "ironcore-mesh",
        "iat":          <unix-seconds>,
        "exp":          <unix-seconds + 300>,
        "capabilities": { ... }
    }.<signature>
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict

from ironcore.mesh.discovery import NodeInfo

logger = logging.getLogger(__name__)

_TOKEN_EXPIRY_SECONDS: int = 300  # 5 minutes — module-level so tests can patch it
_ISSUER: str = "ironcore-mesh"   # module-level so tests can patch it


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    # Re-add stripped padding before decoding
    padding = (4 - len(s) % 4) % 4
    return base64.urlsafe_b64decode(s + "=" * padding)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

class MeshAuthError(Exception):
    """Raised when an agent JWT cannot be verified."""


class AgentJWT:
    """Issue and verify inter-node JWT tokens.

    Usage::

        jwt = AgentJWT(shared_secret=os.environ["IRONCORE_MESH_SHARED_SECRET"])
        token = jwt.issue(this_node)
        payload = jwt.verify(token)          # raises MeshAuthError on failure
    """

    def __init__(self, shared_secret: str) -> None:
        if not shared_secret:
            raise ValueError("shared_secret cannot be empty")
        self._secret = shared_secret.encode()

    def issue(self, requesting_node: NodeInfo) -> str:
        """Create a signed JWT for *requesting_node*.

        The token expires after ``_TOKEN_EXPIRY_SECONDS`` seconds (default 300).
        """
        now = int(time.time())
        header = {"alg": "HS256", "typ": "JWT"}
        payload: Dict[str, Any] = {
            "sub": requesting_node.node_id,
            "iss": _ISSUER,
            "iat": now,
            "exp": now + _TOKEN_EXPIRY_SECONDS,
            "capabilities": requesting_node.capabilities.model_dump(),
        }
        header_enc = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        payload_enc = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
        signing_input = f"{header_enc}.{payload_enc}".encode()
        signature = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        return f"{header_enc}.{payload_enc}.{_b64url_encode(signature)}"

    def verify(self, token: str) -> Dict[str, Any]:
        """Verify *token* and return its decoded payload.

        Raises :exc:`MeshAuthError` if:

        * The token format is invalid (not three dot-separated parts).
        * The HMAC signature does not match.
        * The ``iss`` claim is not ``"ironcore-mesh"``.
        * The token has expired (``exp < now``).
        """
        parts = token.split(".")
        if len(parts) != 3:
            raise MeshAuthError(
                f"Invalid token format: expected 3 parts, got {len(parts)}"
            )
        header_enc, payload_enc, sig_enc = parts

        # Verify signature first (constant-time comparison)
        signing_input = f"{header_enc}.{payload_enc}".encode()
        expected_sig = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        expected_sig_enc = _b64url_encode(expected_sig)
        if not hmac.compare_digest(sig_enc, expected_sig_enc):
            raise MeshAuthError("Invalid token signature")

        # Decode payload
        try:
            payload: Dict[str, Any] = json.loads(_b64url_decode(payload_enc))
        except Exception as exc:
            raise MeshAuthError(f"Cannot decode token payload: {exc}") from exc

        # Validate issuer
        if payload.get("iss") != "ironcore-mesh":
            raise MeshAuthError(
                f"Invalid issuer: expected 'ironcore-mesh', got {payload.get('iss')!r}"
            )

        # Validate expiry
        if payload.get("exp", 0) < int(time.time()):
            raise MeshAuthError("Token has expired")

        return payload
