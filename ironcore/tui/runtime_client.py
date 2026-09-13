from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

STORE_PATH = Path.home() / ".ironcore" / "runtime_store.json"


def _load_store() -> dict[str, Any]:
    if not STORE_PATH.exists():
        return {"token_profiles": {}, "google_maps": {"api_key": ""}}
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"token_profiles": {}, "google_maps": {"api_key": ""}}


def _save_store(data: dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _mask_key(raw: str) -> str:
    if not raw:
        return ""
    if len(raw) < 8:
        return "*" * len(raw)
    return f"{raw[:4]}...{raw[-4:]}"


def list_token_profiles() -> list[dict[str, Any]]:
    store = _load_store()
    rows: list[dict[str, Any]] = []
    for profile_id, item in (store.get("token_profiles") or {}).items():
        expires_at = item.get("expires_at")
        now = int(time.time())
        expired = bool(expires_at and expires_at < now)
        expiring_soon = bool(expires_at and 0 < (expires_at - now) <= 3 * 24 * 3600)
        rows.append(
            {
                "profile_id": profile_id,
                "environment": item.get("environment", "cloud"),
                "scopes": item.get("scopes", []),
                "expires_at": expires_at,
                "last_used_at": item.get("last_used_at"),
                "revoked": bool(item.get("revoked", False)),
                "expired": expired,
                "expiring_soon": expiring_soon,
                "has_token": bool(item.get("token")),
            }
        )
    rows.sort(key=lambda x: x["profile_id"])
    return rows


def save_token_profile(
    profile_id: str,
    token: str,
    environment: str = "cloud",
    scopes: list[str] | None = None,
    expires_in_days: int | None = None,
) -> dict[str, Any]:
    profile_id = profile_id.strip()
    store = _load_store()
    profiles = store.setdefault("token_profiles", {})

    expires_at = None
    if isinstance(expires_in_days, int) and expires_in_days > 0:
        expires_at = int(time.time()) + expires_in_days * 24 * 3600

    profiles[profile_id] = {
        "token": token,
        "environment": environment,
        "scopes": scopes or [],
        "expires_at": expires_at,
        "last_used_at": None,
        "revoked": False,
    }

    _save_store(store)
    return {"profile_id": profile_id}


def use_token_profile(profile_id: str) -> dict[str, Any]:
    store = _load_store()
    profile = (store.get("token_profiles") or {}).get(profile_id, {})
    token = str(profile.get("token") or "")
    if token:
        profile["last_used_at"] = int(time.time())
        profile["revoked"] = False
        (store.get("token_profiles") or {})[profile_id] = profile
        _save_store(store)
    return {"profile_id": profile_id, "token": token}


def revoke_token_profile(profile_id: str) -> dict[str, Any]:
    store = _load_store()
    profiles = store.get("token_profiles") or {}
    profile = profiles.get(profile_id)
    if profile is None:
        return {"profile_id": profile_id, "revoked": False}
    profile["revoked"] = True
    profiles[profile_id] = profile
    _save_store(store)
    return {"profile_id": profile_id, "revoked": True}


def fetch_google_maps_key_status() -> dict[str, Any]:
    store = _load_store()
    raw = str((store.get("google_maps") or {}).get("api_key") or "")
    return {
        "has_key": bool(raw),
        "masked_key": _mask_key(raw),
    }


def save_google_maps_key(api_key: str) -> dict[str, Any]:
    store = _load_store()
    store["google_maps"] = {"api_key": api_key}
    _save_store(store)
    return fetch_google_maps_key_status()


def delete_google_maps_key() -> dict[str, Any]:
    store = _load_store()
    store["google_maps"] = {"api_key": ""}
    _save_store(store)
    return {"has_key": False, "masked_key": ""}
