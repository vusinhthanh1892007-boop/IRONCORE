"""
IAM API Routes — Phase 5, Security V3.

Endpoints consumed by ChatGPT UI V3 (IAM Management panel):

  GET  /api/enterprise/iam/users             → list users (masked email/info)
  GET  /api/enterprise/iam/roles             → list roles + permissions
  POST /api/enterprise/iam/roles             → create role
  PUT  /api/enterprise/iam/roles/{id}        → update permissions
  DELETE /api/enterprise/iam/roles/{id}      → delete role (if unused)
  GET  /api/enterprise/iam/sso/config        → active SSO provider config (masked)
  GET  /api/enterprise/iam/sso/mappings      → group→role mappings
  GET  /api/enterprise/iam/vault/bindings    → secret binding names (no values)

NOTE: This module works with in-memory stores so it can be used without a live
Vault/SSO endpoint. Replace with real SSOManager/VaultSecretsManager via
set_iam() injection at server startup.

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from ironcore.api.enterprise_auth import require_enterprise, require_admin, EnterprisePrincipal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["IAM"])

# In-memory stores (replaced/extended via set_iam() at startup)
_sso_manager = None
_vault_client = None

# Simple in-memory role store (used when no persistent IAM DB is connected)
_roles: Dict[str, Dict[str, Any]] = {
    "admin": {
        "id": "admin",
        "name": "Administrator",
        "permissions": ["*"],
        "description": "Full access to all resources",
        "created_at": 0.0,
        "members": [],
    },
    "approver": {
        "id": "approver",
        "name": "Approver",
        "permissions": ["hitl:approve", "hitl:reject", "hitl:view"],
        "description": "Can approve/reject HITL requests",
        "created_at": 0.0,
        "members": [],
    },
    "viewer": {
        "id": "viewer",
        "name": "Viewer",
        "permissions": ["*.view"],
        "description": "Read-only access",
        "created_at": 0.0,
        "members": [],
    },
}

# Sample vault binding names (no values ever exposed)
_vault_bindings: List[Dict[str, str]] = [
    {"name": "llm/anthropic_api_key", "description": "Anthropic Claude API Key", "status": "bound"},
    {"name": "llm/openai_api_key", "description": "OpenAI API Key", "status": "bound"},
    {"name": "sso/client_secret", "description": "SSO Client Secret", "status": "bound"},
    {"name": "db/main_password", "description": "Main Database Password", "status": "bound"},
]


def set_iam(sso_manager: Any = None, vault_client: Any = None) -> None:
    global _sso_manager, _vault_client
    _sso_manager = sso_manager
    _vault_client = vault_client
    logger.info("[IAMRoutes] IAM singletons registered.")


# ── Request models ─────────────────────────────────────────────────────────────

class CreateRoleRequest(BaseModel):
    name: str
    permissions: List[str]
    description: str = ""


class UpdateRoleRequest(BaseModel):
    name: Optional[str] = None
    permissions: Optional[List[str]] = None
    description: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mask_email(email: str) -> str:
    """Mask email: user@domain.com → u***@domain.com."""
    if "@" not in email:
        return "****"
    local, domain = email.split("@", 1)
    return local[0] + "***@" + domain if len(local) > 1 else "****@" + domain


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> List[Dict[str, Any]]:
    """
    GET /api/enterprise/iam/users

    Return a list of IAM users with masked email addresses.
    In this implementation, we derive users from role member lists.
    """
    seen: Dict[str, Dict[str, Any]] = {}
    for role_id, role in _roles.items():
        for member in role.get("members", []):
            user_id = member if isinstance(member, str) else member.get("id", "unknown")
            if user_id not in seen:
                seen[user_id] = {
                    "user_id": user_id,
                    "masked_email": _mask_email(user_id if "@" in user_id else f"{user_id}@internal"),
                    "roles": [role_id],
                }
            else:
                seen[user_id]["roles"].append(role_id)

    # Return at least a placeholder if no users yet
    if not seen:
        return [{"user_id": "system", "masked_email": "s****@internal", "roles": ["admin"]}]
    return list(seen.values())


@router.get("/roles")
async def list_roles(
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> List[Dict[str, Any]]:
    """
    GET /api/enterprise/iam/roles

    Return all roles with their permissions.
    """
    return list(_roles.values())


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(
    body: CreateRoleRequest,
    _: EnterprisePrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """
    POST /api/enterprise/iam/roles

    Create a new IAM role.
    """
    if not body.name.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Role name must not be empty")
    role_id = body.name.lower().replace(" ", "_")
    if role_id in _roles:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Role '{role_id}' already exists")
    role = {
        "id": role_id,
        "name": body.name,
        "permissions": body.permissions,
        "description": body.description,
        "created_at": time.time(),
        "members": [],
    }
    _roles[role_id] = role
    logger.info("[IAMRoutes] Role created: %s", role_id)
    return role


@router.put("/roles/{role_id}")
async def update_role(
    role_id: str,
    body: UpdateRoleRequest,
    _: EnterprisePrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """
    PUT /api/enterprise/iam/roles/{role_id}

    Update a role's name, permissions, or description.
    """
    if role_id not in _roles:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Role '{role_id}' not found")
    role = _roles[role_id]
    if body.name is not None:
        role["name"] = body.name
    if body.permissions is not None:
        role["permissions"] = body.permissions
    if body.description is not None:
        role["description"] = body.description
    _roles[role_id] = role
    return role


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: str,
    _: EnterprisePrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """
    DELETE /api/enterprise/iam/roles/{role_id}

    Delete a role (only if it has no members).
    """
    if role_id not in _roles:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Role '{role_id}' not found")
    role = _roles[role_id]
    if role.get("members"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Role '{role_id}' still has {len(role['members'])} member(s) — cannot delete"
        )
    del _roles[role_id]
    logger.info("[IAMRoutes] Role deleted: %s", role_id)
    return {"deleted": True, "role_id": role_id}


@router.get("/sso/config")
async def get_sso_config(
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> Dict[str, Any]:
    """
    GET /api/enterprise/iam/sso/config

    Return active SSO provider config with secrets masked.
    """
    import os
    return {
        "provider": os.getenv("IRONCORE_SSO_PROVIDER", "oidc"),
        "client_id": os.getenv("IRONCORE_SSO_CLIENT_ID", ""),
        "client_secret": "****" if os.getenv("IRONCORE_SSO_CLIENT_SECRET") else "(not set)",
        "redirect_uri": os.getenv("IRONCORE_SSO_REDIRECT_URI", "https://ironcore.internal/auth/callback"),
        "scopes": os.getenv("IRONCORE_SSO_SCOPES", "openid email profile groups").split(),
        "tenant_id": os.getenv("IRONCORE_SSO_TENANT_ID", ""),
        "domain": os.getenv("IRONCORE_SSO_DOMAIN", ""),
        "discovery_url": os.getenv("IRONCORE_SSO_DISCOVERY_URL", ""),
        "enabled": bool(os.getenv("IRONCORE_SSO_CLIENT_ID")),
    }


@router.get("/sso/mappings")
async def get_sso_mappings(
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> List[Dict[str, str]]:
    """
    GET /api/enterprise/iam/sso/mappings

    Return configured SSO group → IronCore role mappings.
    Derived from IRONCORE_SSO_GROUP_MAPPINGS env var (JSON).
    """
    import os
    import json as _json
    raw = os.getenv("IRONCORE_SSO_GROUP_MAPPINGS", "{}")
    try:
        mapping: Dict[str, str] = _json.loads(raw)
    except Exception:  # noqa: BLE001
        mapping = {}

    if not mapping:
        # Return example mapping to show the structure
        mapping = {
            "IT-Admins": "admin",
            "RiskManagement": "approver",
            "ReadOnly-Access": "viewer",
        }

    return [
        {"idp_group": group, "ironcore_role": role}
        for group, role in mapping.items()
    ]


@router.get("/vault/bindings")
async def get_vault_bindings(
    _: EnterprisePrincipal = Depends(require_enterprise),
) -> List[Dict[str, str]]:
    """
    GET /api/enterprise/iam/vault/bindings

    Return secret binding names only — values are NEVER exposed.
    """
    return _vault_bindings
