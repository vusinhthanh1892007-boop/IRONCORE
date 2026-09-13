"""
IronCore Tool: ip_geolocate
============================
Geolocate an IP address or look up the caller's own IP info.
Uses ip-api.com (free, no API key, 45 req/min limit) or
ip-api.com Pro (IPAPI_KEY env var) for HTTPS + higher limits.
"""

from __future__ import annotations

import logging
import os

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)


@skill(
    name="ip_geolocate",
    version="1.0.0",
    description="Geolocate an IP address: country, city, ISP, timezone, lat/lon. Free via ip-api.com.",
    author="brain",
    tags=["ip", "geolocation", "network", "location", "free"],
    risk_level=RiskLevel.LOW,
    requires_network=True,
    parameters=[
        SkillParameterSchema(
            name="ip",
            type="string",
            description="IPv4 or IPv6 address to look up. Leave empty to look up the server's own public IP.",
            required=False,
            default="",
        ),
        SkillParameterSchema(
            name="fields",
            type="string",
            description="Comma-separated fields to include: 'country,city,isp,timezone,lat,lon,org,asname,mobile,proxy'. Default returns all.",
            required=False,
            default="",
        ),
        SkillParameterSchema(
            name="lang",
            type="string",
            description="Language for city/country names: 'en','de','es','pt-BR','fr','ja','zh-CN','ru'",
            required=False,
            default="en",
        ),
    ],
)
async def ip_geolocate(
    ip: str = "",
    fields: str = "",
    lang: str = "en",
) -> dict:
    """Geolocate an IP address using ip-api.com."""
    import httpx

    ip = (ip or "").strip()
    lang = (lang or "en").strip()

    # ip-api.com: free HTTP (no key), Pro HTTPS (IPAPI_KEY)
    api_key = os.environ.get("IPAPI_KEY", "")

    if api_key:
        # Pro endpoint: HTTPS, higher rate limits
        base_url = f"https://pro.ip-api.com/json/{ip}"
        params: dict = {"key": api_key, "lang": lang}
    else:
        # Free endpoint: HTTP only, 45 req/min
        base_url = f"http://ip-api.com/json/{ip}"
        params = {"lang": lang}

    # Always request these useful fields
    default_fields = (
        "status,message,country,countryCode,region,regionName,"
        "city,zip,lat,lon,timezone,isp,org,as,asname,mobile,proxy,hosting,query"
    )
    params["fields"] = fields if fields.strip() else default_fields

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(base_url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("ip_geolocate failed: %s", exc)
        return {"error": str(exc)}

    if data.get("status") == "fail":
        msg = data.get("message", "Unknown error")
        return {"error": f"ip-api.com: {msg}", "ip": ip or "own"}

    # Clean up response
    data.pop("status", None)
    if not ip:
        data["note"] = "Lookup performed on server's own public IP"

    return data
